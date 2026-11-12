import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from extension.tools import publish_store


RESOURCE = "publishers/test-publisher/items/test-item"
PUBLISHED = {
    "name": RESOURCE,
    "publishedItemRevisionStatus": {"distributionChannels": [{"crxVersion": "1.0.2"}]},
}


class ChromeWebStoreReleaseTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.archive = Path(directory.name) / "extension.zip"
        with ZipFile(self.archive, "w") as package:
            package.writestr("manifest.json", json.dumps({"version": "1.0.6"}))

    @patch.object(publish_store, "request")
    def test_uploads_zip_and_submits_same_listing(self, request):
        request.side_effect = [
            PUBLISHED,
            {"name": RESOURCE, "crxVersion": "1.0.6", "uploadState": "SUCCEEDED"},
            {"name": RESOURCE, "state": "PENDING_REVIEW"},
        ]
        publish_store.submit(RESOURCE, "test-token", self.archive, "DEFAULT_PUBLISH")

        status, upload, review = request.call_args_list
        self.assertEqual(status.args[0], f"/v2/{RESOURCE}:fetchStatus")
        self.assertEqual(upload.args[0], f"/upload/v2/{RESOURCE}:upload")
        self.assertEqual(upload.kwargs["data"], self.archive.read_bytes())
        self.assertEqual(review.args[0], f"/v2/{RESOURCE}:publish")
        self.assertEqual(json.loads(review.kwargs["data"]), {"publishType": "DEFAULT_PUBLISH"})

    @patch.object(publish_store.time, "sleep")
    @patch.object(publish_store, "request")
    def test_waits_for_async_upload_before_submitting(self, request, sleep):
        request.side_effect = [
            PUBLISHED,
            {"name": RESOURCE, "uploadState": "IN_PROGRESS"},
            {"name": RESOURCE, "lastAsyncUploadState": "IN_PROGRESS"},
            {"name": RESOURCE, "lastAsyncUploadState": "SUCCEEDED"},
            {"name": RESOURCE, "state": "PENDING_REVIEW"},
        ]
        publish_store.submit(RESOURCE, "test-token", self.archive, "STAGED_PUBLISH")
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(json.loads(request.call_args.kwargs["data"]), {"publishType": "STAGED_PUBLISH"})

    @patch.object(publish_store, "request")
    def test_does_not_replace_active_submission(self, request):
        for state in ("PENDING_REVIEW", "STAGED"):
            with self.subTest(state=state):
                request.reset_mock()
                request.return_value = {**PUBLISHED, "submittedItemRevisionStatus": {"state": state}}
                with self.assertRaisesRegex(RuntimeError, "A submission already exists"):
                    publish_store.submit(RESOURCE, "test-token", self.archive, "DEFAULT_PUBLISH")
                request.assert_called_once()

    @patch.object(publish_store, "request")
    def test_rejects_already_published_version(self, request):
        request.return_value = {
            "name": RESOURCE,
            "publishedItemRevisionStatus": {"distributionChannels": [{"crxVersion": "1.0.6.0"}]},
        }
        with self.assertRaisesRegex(RuntimeError, "must be newer"):
            publish_store.submit(RESOURCE, "test-token", self.archive, "DEFAULT_PUBLISH")
        request.assert_called_once()

    @patch.object(publish_store, "request")
    def test_does_not_submit_if_upload_fails(self, request):
        request.side_effect = [PUBLISHED, {"name": RESOURCE, "uploadState": "FAILED"}]
        with self.assertRaisesRegex(RuntimeError, "upload did not succeed"):
            publish_store.submit(RESOURCE, "test-token", self.archive, "DEFAULT_PUBLISH")
        self.assertEqual(request.call_count, 2)
