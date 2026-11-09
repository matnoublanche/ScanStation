"""Paperless delivery state machine. Never hold a database transaction during HTTP."""
import fcntl
import json
from pathlib import Path
import time
import uuid
from urllib.parse import urlsplit

import requests

from jobqueue import Queue, STATE


def rows(data):
    return data if isinstance(data, list) else data["results"]


def endpoint(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("paperless_url must be an HTTPS base URL")
    return url.rstrip("/") + "/api/"


def update(db, row, state, **fields):
    fields.update(state=state, updated=time.time())
    with db:
        db.execute("UPDATE deliveries SET " + ",".join(k+"=?" for k in fields) + " WHERE id=?",
                   (*fields.values(), row["id"]))


def advance(db, row):
    state = row["state"]
    task = row["task"]
    try:
        api = endpoint(row["url"])
        token = Path(row["token_file"]).expanduser().read_text().strip()
        if not token:
            raise ValueError("Empty Paperless token file")
        def call(method, route, **kwargs):
            r = requests.request(method, api+route, headers={"Authorization": "Token "+token},
                                 timeout=(8, 75), allow_redirects=False, **kwargs)
            if 300 <= r.status_code < 400:
                raise ValueError("Unexpected API redirect; check paperless_url")
            r.raise_for_status()
            return r.json() if r.content else None

        if state == "queued":
            matches = [tag for tag in rows(call("GET", "tags/", params={"name__iexact":row["tag_name"]}))
                       if tag["name"].casefold() == row["tag_name"].casefold()]
            if len(matches) != 1:
                raise ValueError("Configured inbox tag was not uniquely found")
            tag = matches[0]
            path = Path(row["path"])
            form = {"title": path.stem}
            if not tag.get("is_inbox_tag"):
                form["tags"] = str(tag["id"])
            with path.open("rb") as source:
                # After this commit a crash or lost response must never cause an automatic repost.
                update(db, row, "sending", tag_id=tag["id"], explicit_tag=int("tags" in form))
                state = "sending"
                task = str(uuid.UUID(str(call("POST", "documents/post_document/", data=form,
                                             files={"document": (path.name, source, "application/pdf")}))))
            update(db, row, "consuming", task=task, due=time.time()+2, attempts=0, error=None)
        elif state == "consuming":
            tasks = [t for t in rows(call("GET", "tasks/", params={"task_id":task})) if t["task_id"] == task]
            if not tasks or tasks[0]["status"] in ("PENDING","STARTED","RETRY","RECEIVED","PROGRESS"):
                update(db, row, state, due=time.time()+4)
                return
            item = tasks[0]
            if item["status"] != "SUCCESS":
                raise ValueError("Paperless consumption ended with status " + item["status"])
            ids = item.get("related_document_ids") or [item.get("related_document")]
            if len(ids) != 1 or not ids[0]:
                raise ValueError("Consumption succeeded without a unique document ID")
            update(db, row, "verifying", doc=int(ids[0]), due=time.time(), attempts=0)
        else:
            doc = call("GET", f"documents/{row['doc']}/")
            if row["tag_id"] in doc["tags"]:
                update(db, row, "delivered", error=None)
            elif not row["repair"]:
                call("POST", "documents/bulk_edit/", json={"documents":[row["doc"]],"method":"add_tag",
                                                          "parameters":{"tag":row["tag_id"]}})
                update(db, row, "verifying", repair=1, due=time.time()+3, attempts=0)
            elif row["attempts"] < 15:
                update(db, row, "verifying", due=time.time()+4, attempts=row["attempts"]+1)
            else:
                raise ValueError("Inbox tag missing after repair")
    except (OSError, ValueError, KeyError, requests.RequestException) as exc:
        http = exc.response.status_code if isinstance(exc, requests.HTTPError) else None
        # Avoid leaking request headers or server response bodies into logs.
        reason = f"HTTP {http}" if http else (str(exc) if type(exc) is ValueError else type(exc).__name__)
        if state == "sending":
            if http in (400,401,403,404,413,415,422,429):
                retry = "queued" if http == 429 else "failed"
            else:
                retry = "uncertain"
        elif isinstance(exc, requests.RequestException) and (not http or http == 429 or http >= 500):
            retry = state
        else:
            retry = "failed"
        count = row["attempts"]+1
        update(db, row, retry, error=reason, attempts=count, due=time.time()+min(300, 2**min(count,8)))


def serve():
    q = Queue()
    with (STATE/"delivery.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with q.db:
            q.db.execute("UPDATE deliveries SET state='uncertain',error='Interrupted during upload' WHERE state='sending'")
        while True:
            row = q.db.execute("""SELECT * FROM deliveries WHERE state IN ('queued','consuming','verifying')
                               AND due<=? ORDER BY due,id LIMIT 1""",(time.time(),)).fetchone()
            if row is None:
                time.sleep(.5)
            else:
                advance(q.db, row)


if __name__ == "__main__":
    serve()
