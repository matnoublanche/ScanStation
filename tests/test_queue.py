import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import jobqueue


class QueueTests(unittest.TestCase):
    def test_restart_and_independent_batches(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(jobqueue, "STATE", Path(tmp)):
            q = jobqueue.Queue()
            q.submit(Path(tmp)/"A", {"mode": "page"})
            self.assertEqual(q.claim()["id"], "A")
            q.record("A", {"event": "progress", "stage": "name"})
            q.submit(Path(tmp)/"B", {"mode": "sheet"})
            self.assertEqual([r["state"] for r in q.snapshot()], ["processing", "queued"])
            q.db.close()
            q = jobqueue.Queue()
            q.recover()
            self.assertEqual(q.claim()["id"], "A")
            q.record("A", {"event": "completed", "pdf": ["A/one.pdf"]})
            self.assertEqual(q.claim()["id"], "B")
            q.record("B", {"event": "error", "message": "test error"})
            result = []
            q.wait("A", result.append)
            self.assertEqual(result[-1]["pdf"], ["A/one.pdf"])
            self.assertEqual(q.snapshot()[-1]["state"], "failed")
            q.db.close()
