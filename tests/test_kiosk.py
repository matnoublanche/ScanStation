import unittest
from kiosk.bridge import view


class KioskTests(unittest.TestCase):
    def setUp(self):
        self.state = dict(mode="page", status="ready", loaded=False, jobs=[], deliveries=[])

    def test_selection_and_scan_are_separate(self):
        model = view(self.state, 100)
        self.assertTrue(model["select"])
        self.assertFalse(model["scan"])
        self.state["loaded"] = True
        self.assertTrue(view(self.state, 100)["scan"])

    def test_background_work_allows_another_capture(self):
        self.state.update(loaded=True, jobs=[dict(state="processing", progress=dict(
            stage="filter", side=3, total_sides=8))])
        model = view(self.state, 100)
        self.assertIn("3 of 8", model["task"])
        self.assertTrue(model["scan"])

    def test_capture_multipass_and_inbox(self):
        self.state.update(status="scan", progress=dict(stage="captured", side=4))
        self.assertIn("sheet 2", view(self.state, 100)["scanner"])
        self.state.update(status="waiting", loaded=True)
        self.assertTrue(view(self.state, 100)["waiting"])
        self.assertFalse(view(self.state, 100)["select"])
        self.state.update(status="ready", deliveries=[dict(state="delivered", updated=95)])
        self.assertIn("Inbox verified", view(self.state, 100)["task"])

    def test_french_labels_and_live_counts(self):
        self.state.update(status="scan", progress=dict(stage="captured", side=2, captured=6))
        model = view(self.state, 100, "fr")
        self.assertIn("feuille 3, verso", model["scanner"])

    def test_progress_includes_new_batches_and_verified_delivery(self):
        from kiosk.workload import Workload
        meter = Workload()
        self.state.update(status="scan", progress={"captured": 1})
        self.assertEqual(meter.measure(self.state, 0), -2)
        a = dict(id="A", state="processing", sides=4, upload=True, progress=dict(processed=2))
        self.state.update(status="ready", jobs=[a])
        self.assertEqual(meter.measure(self.state, 1), 42)
        b = dict(id="B", state="queued", sides=2, upload=False, progress=None)
        self.state["jobs"].append(b)
        self.assertEqual(meter.measure(self.state, 2), 35)
        a.update(state="completed", progress=dict(pdf=["1","2"]))
        b.update(state="completed", progress=dict(pdf=["3"]))
        self.state["delivery_counts"] = {"A":dict(total=2, verified=1)}
        self.assertEqual(meter.measure(self.state, 3), 95)
        self.state["delivery_counts"]["A"]["verified"] = 2
        self.assertEqual(meter.measure(self.state, 4), 100)
        self.assertEqual(meter.measure(self.state, 35), -1)
