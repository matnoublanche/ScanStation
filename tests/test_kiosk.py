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
