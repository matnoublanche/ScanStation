"""Durable handoff between completed acquisitions and one PDF worker."""
import json
import os
from pathlib import Path
import sqlite3
import time

STATE = Path(os.environ.get("XDG_STATE_HOME") or Path.home()/".local/state") / "scanstation"


class Queue:
    def __init__(self):
        STATE.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(STATE / "jobs.sqlite3", timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, directory TEXT UNIQUE NOT NULL, options TEXT NOT NULL,
                state TEXT NOT NULL, queued REAL NOT NULL, updated REAL NOT NULL, latest TEXT);
            CREATE TABLE IF NOT EXISTS deliveries (
                id INTEGER PRIMARY KEY, job TEXT NOT NULL, path TEXT NOT NULL, url TEXT NOT NULL,
                token_file TEXT NOT NULL, tag_name TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued',
                due REAL NOT NULL DEFAULT 0, updated REAL NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
                task TEXT, doc INTEGER, tag_id INTEGER, explicit_tag INTEGER, repair INTEGER DEFAULT 0,
                error TEXT, UNIQUE(job,path));
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY, job TEXT NOT NULL, at REAL NOT NULL, data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS event_job ON events(job, seq);
        """)

    def submit(self, folder, options):
        now = time.time()
        with self.db:
            self.db.execute("INSERT INTO jobs VALUES (?,?,?,'queued',?,?,NULL)",
                            (folder.name, str(folder), json.dumps(options), now, now))

    def recover(self):
        # Called only after taking the exclusive worker lock.
        with self.db:
            self.db.execute("UPDATE jobs SET state='queued' WHERE state='processing'")

    def claim(self):
        with self.db:
            row = self.db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY queued,rowid LIMIT 1").fetchone()
            if row:
                self.db.execute("UPDATE jobs SET state='processing',updated=? WHERE id=?", (time.time(), row["id"]))
        return row

    def record(self, job, item):
        item = dict(item, job_id=job)
        data = json.dumps(item, ensure_ascii=False)
        state = {"completed": "completed", "error": "failed"}.get(item["event"], "processing")
        now = time.time()
        with self.db:
            if state == "completed":
                options = json.loads(self.db.execute("SELECT options FROM jobs WHERE id=?", (job,)).fetchone()[0])
                if options.get("paperless_url"):
                    self.db.executemany("""INSERT OR IGNORE INTO deliveries
                        (job,path,url,token_file,tag_name,due,updated) VALUES (?,?,?,?,?,?,?)""",
                        [(job,p,options["paperless_url"],options["paperless_token_file"],
                          options["paperless_inbox_tag"],now,now) for p in item["pdf"]])
            self.db.execute("INSERT INTO events(job,at,data) VALUES (?,?,?)", (job, now, data))
            self.db.execute("UPDATE jobs SET state=?,latest=?,updated=? WHERE id=?", (state,data,now,job))

    def snapshot(self):
        rows = self.db.execute("""SELECT id,state,queued,updated,latest,options FROM jobs
            WHERE state IN ('queued','processing') OR id IN (SELECT job FROM deliveries WHERE state!='delivered') OR id IN
            (SELECT id FROM jobs WHERE state IN ('completed','failed') ORDER BY updated DESC LIMIT 8)
            ORDER BY queued,rowid""")
        result = []
        for row in rows:
            opts = json.loads(row["options"])
            result.append(dict(id=row["id"], state=row["state"], queued=row["queued"], updated=row["updated"],
                               sides=opts.get("sides"), mode=opts.get("mode"), upload=bool(opts.get("paperless_url")),
                               progress=json.loads(row["latest"]) if row["latest"] else None))
        return result

    def delivery_counts(self):
        # Include all PDFs, including verified imports outside the short UI history.
        return {r["job"]: dict(total=r["total"], verified=r["verified"], updated=r["updated"])
                for r in self.db.execute("""SELECT job, count(*) total, sum(state='delivered') verified,
                    max(updated) updated FROM deliveries GROUP BY job
                    HAVING verified < total OR updated > ?""", (time.time()-30,))}

    def delivery_status(self):
        return [dict(r) for r in self.db.execute("""SELECT id,job,path,state,task,doc,tag_id,explicit_tag,repair,error,updated
            FROM deliveries WHERE state!='delivered' OR id IN
            (SELECT id FROM deliveries WHERE state='delivered' ORDER BY updated DESC LIMIT 8)
            ORDER BY id""")]

    def retry_delivery(self, number):
        with self.db:
            row = self.db.execute("SELECT * FROM deliveries WHERE id=?", (number,)).fetchone()
            if not row or row["state"] not in ("failed","uncertain"):
                raise ValueError("Delivery must be failed or uncertain")
            state = "verifying" if row["doc"] else ("consuming" if row["task"] else "queued")
            self.db.execute("UPDATE deliveries SET state=?,attempts=0,repair=0,error=NULL,due=0 WHERE id=?",
                            (state, number))

    def wait(self, job, emit):
        cursor = 0
        while True:
            rows = self.db.execute("SELECT seq,data FROM events WHERE job=? AND seq>? ORDER BY seq",
                                   (job, cursor)).fetchall()
            for row in rows:
                cursor = row["seq"]
                data = json.loads(row["data"])
                if data["event"] == "error":
                    raise ValueError(data["message"])
                emit(data)
                if data["event"] == "completed":
                    return
            time.sleep(.25)
