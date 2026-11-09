"""Estimate overall progress by measured work across overlapping batches."""
class Workload:
    def __init__(self):
        self.members = {}
        self.finished = None

    def measure(self, state, now):
        jobs = state.get("jobs", [])
        counts = state.get("delivery_counts", {})
        capture = state["status"] in ("scan", "waiting", "finalizing")
        current = {j["id"] for j in jobs if j["state"] in ("queued", "processing")}
        current.update(k for k, d in counts.items() if d["verified"] < d["total"])
        if (current or capture) and self.finished is not None:
            self.members.clear()
            self.finished = None
        for job in jobs:
            key = job["id"]
            if key not in current and key not in self.members:
                continue
            item = job.get("progress") or {}
            sides = job.get("sides") or item.get("sides") or item.get("total_sides") or 1
            phase = job["state"]
            # Each side has acquisition and processing work; processing dominates.
            total = sides * (7 if job.get("upload") else 6)
            done = sides
            if phase == "processing":
                if item.get("stage") == "assemble":
                    done += 4*sides + sides*(item["document"]-1)/max(1,item["total_documents"])
                else:
                    done += 4*min(sides,item.get("processed",0))
            elif phase == "completed":
                done = 6*sides
                if job.get("upload"):
                    d = counts.get(key)
                    if not item.get("pdf") or d is None:
                        done = total
                    else:
                        done += sides*d["verified"]/d["total"]
            elif phase == "failed":
                done = self.members.get(key,(0,total))[0]
            self.members[key] = (done,total)
        # A long-running delivery can outlive a job's place in the recent list.
        for key in self.members.keys() - {j["id"] for j in jobs}:
            if key not in current:
                total = self.members[key][1]
                self.members[key] = (total,total)
        if not current and not capture:
            if self.finished is None:
                self.finished = now
            if now-self.finished > 20:
                self.members.clear()
        acquired = (state.get("progress") or {}).get("captured",0) if capture else 0
        if capture and not self.members:
            return -2  # unknown feeder length: moving segment, no invented percentage
        done = sum(v[0] for v in self.members.values()) + acquired
        total = sum(v[1] for v in self.members.values()) + acquired*7
        if not total:
            return -1
        value = int(100*done/total)
        return min(99,value) if current or capture else value
