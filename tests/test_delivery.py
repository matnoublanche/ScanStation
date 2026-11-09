import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
import uuid
import requests

import delivery
import jobqueue


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name)
        override = patch.object(jobqueue, "STATE", path)
        override.start()
        self.addCleanup(override.stop)
        self.q = jobqueue.Queue()
        self.addCleanup(self.q.db.close)
        token = path/"key"
        token.write_text("test-token")
        self.pdf = path/"Example.pdf"
        self.pdf.write_bytes(b"%PDF fixture")
        self.q.submit(path/"job-a", dict(paperless_url="https://example.invalid",
                      paperless_token_file=str(token), paperless_inbox_tag="inbox"))
        result = dict(event="completed", pdf=[str(self.pdf)])
        self.q.record("job-a", result)
        self.q.record("job-a", result)
        self.assertEqual(len(self.q.delivery_status()), 1)

    def step(self, replies):
        row = self.q.db.execute("SELECT * FROM deliveries").fetchone()
        responses = []
        for value in replies:
            if isinstance(value, BaseException):
                responses.append(value)
            else:
                response = Mock(status_code=200, content=b"data")
                response.json.return_value = value
                responses.append(response)
        with patch.object(requests, "request", side_effect=responses) as request:
            delivery.advance(self.q.db, row)
        return request

    def test_task_and_verified_default_tag(self):
        task = str(uuid.uuid4())
        req = self.step([[dict(name="inbox",id=3,is_inbox_tag=True)],task])
        self.assertNotIn("tags", req.call_args.kwargs["data"])
        self.step([[dict(task_id=task,status="SUCCESS",related_document_ids=[42])]])
        self.step([dict(tags=[3])])
        self.assertEqual(self.q.delivery_status()[0]["state"], "delivered")

    def test_uncertain_post_is_not_requeued(self):
        self.step([[dict(name="inbox",id=3,is_inbox_tag=True)],requests.ReadTimeout()])
        self.assertEqual(self.q.delivery_status()[0]["state"], "uncertain")

    def test_missing_tag_added_and_read_back(self):
        task = str(uuid.uuid4())
        req = self.step([[dict(name="inbox",id=3,is_inbox_tag=False)],task])
        self.assertEqual(req.call_args.kwargs["data"]["tags"], "3")
        self.step([[dict(task_id=task,status="SUCCESS",related_document=42)]])
        req = self.step([dict(tags=[8]), {}])
        self.assertEqual(req.call_args.kwargs["json"]["method"], "add_tag")
        self.assertEqual(self.q.delivery_status()[0]["state"], "verifying")
        self.step([dict(tags=[3,8])])
        self.assertEqual(self.q.delivery_status()[0]["state"], "delivered")
