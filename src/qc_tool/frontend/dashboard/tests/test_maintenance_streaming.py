"""Stream cleanup remains inside the maintenance admission lifetime."""

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.http import FileResponse
from django.http import StreamingHttpResponse
from django.test import RequestFactory
from django.test import SimpleTestCase
from django.test import override_settings

from qc_tool.frontend.dashboard.middleware import MaintenanceModeMiddleware
from qc_tool.frontend.dashboard.services.maintenance import state


class MaintenanceStreamLifetimeTests(SimpleTestCase):
    def setUp(self):
        temporary = self.enterContext(TemporaryDirectory())
        self.enterContext(override_settings(
            QC_TOOL_MAINTENANCE_DIR=Path(temporary) / "maintenance",
            MAINTENANCE_MODE=False,
        ))
        self.request = RequestFactory().get("/deliveries/export.csv")

    def protect(self, response):
        return MaintenanceModeMiddleware(lambda request: response)(self.request)

    def assert_activity_released(self):
        with state.file_lock("activity", blocking=False) as acquired:
            self.assertTrue(acquired)

    def test_unconsumed_source_closes_before_activity_is_released(self):
        cleanup_observations = []

        class Source:
            def __iter__(self):
                return self

            def __next__(self):
                return b"data"

            def close(self):
                with state.file_lock("activity", blocking=False) as acquired:
                    cleanup_observations.append(acquired)

        response = self.protect(StreamingHttpResponse(Source()))
        response.close()
        response.close()

        self.assertEqual(cleanup_observations, [False])
        self.assert_activity_released()

    def test_partially_consumed_generator_cleanup_retains_activity(self):
        cleanup_observations = []

        def chunks():
            try:
                yield b"one"
                yield b"two"
            finally:
                with state.file_lock("activity", blocking=False) as acquired:
                    cleanup_observations.append(acquired)

        response = self.protect(StreamingHttpResponse(chunks()))
        try:
            self.assertEqual(next(iter(response.streaming_content)), b"one")
        finally:
            response.close()

        self.assertEqual(cleanup_observations, [False])
        self.assert_activity_released()

    def test_file_response_retains_its_original_file_closer(self):
        source = BytesIO(b"file bytes")
        response = self.protect(FileResponse(source))
        response.close()

        self.assertTrue(source.closed)
        self.assert_activity_released()

    def test_exhausted_source_cleanup_finishes_before_readiness(self):
        cleanup_observations = []

        class Source:
            def __iter__(self):
                return iter((b"complete",))

            def close(self):
                with state.file_lock("activity", blocking=False) as acquired:
                    cleanup_observations.append(acquired)

        response = self.protect(StreamingHttpResponse(Source()))
        try:
            self.assertEqual(b"".join(response.streaming_content), b"complete")
            with state.file_lock("activity", blocking=False) as acquired:
                self.assertFalse(acquired)
        finally:
            response.close()

        self.assertEqual(cleanup_observations, [False])
        self.assert_activity_released()

    def test_failed_source_cleanup_finishes_before_readiness(self):
        cleanup_observations = []

        class Source:
            def __iter__(self):
                return self

            def __next__(self):
                raise RuntimeError("stream failed")

            def close(self):
                with state.file_lock("activity", blocking=False) as acquired:
                    cleanup_observations.append(acquired)

        response = self.protect(StreamingHttpResponse(Source()))
        try:
            with self.assertRaisesRegex(RuntimeError, "stream failed"):
                list(response.streaming_content)
            with state.file_lock("activity", blocking=False) as acquired:
                self.assertFalse(acquired)
        finally:
            response.close()

        self.assertEqual(cleanup_observations, [False])
        self.assert_activity_released()
