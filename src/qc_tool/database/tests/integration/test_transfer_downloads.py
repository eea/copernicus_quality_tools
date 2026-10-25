"""Download interruption affects a bounded reader, never the retained package."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import RequestFactory, SimpleTestCase

from qc_tool.database.transfers import downloads


class RetainedPackageDownloadTests(SimpleTestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.path = self.root / "package.zip"
        self.data = bytes(range(256)) * 1200
        self.path.write_bytes(self.data)
        self.metadata = {"filename": "qc-tool-database-fixture.zip", "sha256": hashlib.sha256(self.data).hexdigest()}
        self.factory = RequestFactory()

    def response(self, method="GET", **headers):
        request = self.factory.generic(method, "/admin/database/download/", **headers)
        handle = self.path.open("rb")
        response = downloads.response(handle, self.metadata, request)
        self.addCleanup(response.close)
        return response, handle

    def test_full_file_is_a_bounded_retained_stream_with_stable_identity(self):
        response, handle = self.response()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertEqual(response["Accept-Ranges"], "bytes")
        self.assertIn(self.metadata["sha256"], response["ETag"])
        self.assertEqual(int(response["Content-Length"]), len(self.data))
        chunks = list(response.streaming_content)
        self.assertEqual(b"".join(chunks), self.data)
        self.assertTrue(all(len(chunk) <= downloads.BLOCK_SIZE for chunk in chunks))
        response.close()
        self.assertTrue(handle.closed)

    def test_interrupted_stream_can_resume_exact_bytes_without_modifying_file(self):
        first, handle = self.response()
        original_etag = first["ETag"]
        iterator = iter(first.streaming_content)
        prefix = next(iterator)
        first.close()
        self.assertTrue(handle.closed)
        resumed, _ = self.response(HTTP_RANGE="bytes=" + str(len(prefix)) + "-", HTTP_IF_RANGE=original_etag)
        self.assertEqual(resumed.status_code, 206)
        self.assertEqual(prefix + b"".join(resumed.streaming_content), self.data)
        self.assertEqual(self.path.read_bytes(), self.data)
        self.assertEqual(resumed["ETag"], original_etag)

    def test_suffix_and_exact_ranges_serve_only_the_requested_bytes(self):
        for requested, start, end in (("bytes=-3", len(self.data) - 3, len(self.data) - 1),
                                      ("bytes=2-5", 2, 5), ("bytes=2-9999999", 2, len(self.data) - 1)):
            with self.subTest(requested=requested):
                response, _ = self.response(HTTP_RANGE=requested)
                self.assertEqual(response.status_code, 206)
                self.assertEqual(response["Content-Range"], f"bytes {start}-{end}/{len(self.data)}")
                self.assertEqual(b"".join(response.streaming_content), self.data[start:end + 1])

    def test_unsatisfiable_or_multi_ranges_are_bounded_errors_and_close_the_handle(self):
        for value in ("bytes=-0", "bytes=9-2", "bytes=9999999-", "bytes=0-1,3-4", "bytes=-", "x" * 200):
            with self.subTest(value=value):
                response, handle = self.response(HTTP_RANGE=value)
                self.assertEqual(response.status_code, 416)
                self.assertEqual(response["Content-Range"], "bytes */" + str(len(self.data)))
                self.assertTrue(handle.closed)

    def test_head_reports_full_or_range_headers_without_reading_bytes(self):
        full, full_handle = self.response(method="HEAD")
        self.assertEqual(full.status_code, 200)
        self.assertEqual(full.content, b"")
        self.assertTrue(full_handle.closed)
        partial, partial_handle = self.response(method="HEAD", HTTP_RANGE="bytes=2-5")
        self.assertEqual(partial.status_code, 206)
        self.assertEqual(partial["Content-Length"], "4")
        self.assertEqual(partial.content, b"")
        self.assertTrue(partial_handle.closed)

    def test_changed_if_range_identity_uses_a_complete_response(self):
        response, _ = self.response(HTTP_RANGE="bytes=2-5", HTTP_IF_RANGE='"different-package"')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), self.data)
