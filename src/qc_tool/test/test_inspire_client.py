"""INSPIRE client deadlines use elapsed time without depending on live services."""

import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import requests

from qc_tool.worker import inspire


class InspireClientDeadlineTests(TestCase):
    def clock(self):
        clock = SimpleNamespace(value=0)

        def sleep(seconds):
            clock.value += seconds

        self.enterContext(patch.object(inspire.time, "monotonic", side_effect=lambda: clock.value))
        self.enterContext(patch.object(inspire.time, "sleep", side_effect=sleep))
        self.enterContext(patch.object(inspire, "INSPIRE_TEST_RUN_TIMEOUT", 20))
        return clock

    def test_optional_version_probe_has_a_request_timeout(self):
        response = Mock()
        response.json.return_value = {"tag_name": "v2026.1"}
        with patch.object(inspire.requests, "get", return_value=response) as get:
            self.assertEqual(inspire.InspireServiceClient.get_github_validator_version(), "2026.1")
        self.assertEqual(get.call_args.kwargs["timeout"], inspire.INSPIRE_VERSION_TIMEOUT)
        with patch.object(inspire.requests, "get", side_effect=requests.Timeout):
            self.assertIsNone(inspire.InspireServiceClient.get_github_validator_version())

    def test_polling_budget_includes_request_duration(self):
        clock = self.clock()
        response = Mock()
        response.json.return_value = {"val": 0, "max": 1}

        def get(*args, **kwargs):
            clock.value += 6
            return response

        with patch.object(inspire.requests, "get", side_effect=get) as request:
            result, message = inspire.InspireServiceClient.retrieve_test_result("test-run")
        self.assertIsNone(result)
        self.assertIn("timed out after 20 seconds", message)
        self.assertEqual(request.call_count, 2)
        self.assertEqual([call.kwargs["timeout"] for call in request.call_args_list], [15, 4])

    def test_finished_progress_and_report_share_the_budget(self):
        clock = self.clock()
        progress = Mock()
        progress.json.return_value = {"val": 1, "max": 1}
        report = Mock()
        report.json.return_value = {"EtfItemCollection": {"testRuns": {"TestRun": {"status": "PASSED"}}}}
        responses = iter((progress, report))

        def get(*args, **kwargs):
            clock.value += 1
            return next(responses)

        with patch.object(inspire.requests, "get", side_effect=get) as request:
            self.assertEqual(inspire.InspireServiceClient.retrieve_test_result("test-run"), ("PASSED", "ok"))
        self.assertEqual([call.kwargs["timeout"] for call in request.call_args_list], [15, 9])

    def test_deadline_during_poll_wait_does_not_start_another_request(self):
        self.clock()
        with patch.object(inspire, "INSPIRE_TEST_RUN_TIMEOUT", 5), patch.object(inspire.requests, "get") as get:
            result, message = inspire.InspireServiceClient.retrieve_test_result("test-run")
        self.assertIsNone(result)
        self.assertIn("timed out after 5 seconds", message)
        get.assert_not_called()


class InspireClientTransportTests(TestCase):
    def setUp(self):
        self.enterContext(patch.dict(inspire.CONFIG, {"inspire_service_url": "https://validator.test/v2/"}))

    def test_suite_lookup_keeps_service_contract_and_timeout(self):
        response = Mock()
        response.json.return_value = {
            "EtfItemCollection": {"executableTestSuites": {"ExecutableTestSuite": [
                {"id": "other", "label": "Other suite"},
                {"id": "metadata", "label": inspire.INSPIRE_TEST_SUITE_NAME},
            ]}}
        }
        with patch.object(inspire.requests, "get", return_value=response) as get:
            self.assertEqual(inspire.InspireServiceClient.retrieve_test_suite_id(), ("metadata", "ok"))
        get.assert_called_once_with(
            "https://validator.test/v2/ExecutableTestSuites.json",
            timeout=inspire.INSPIRE_SERVER_TIMEOUT,
        )
        response.raise_for_status.assert_called_once_with()

    def test_upload_preserves_xml_bytes_and_normalizes_service_id(self):
        with tempfile.TemporaryDirectory() as directory:
            xml = Path(directory) / "metadata.xml"
            xml.write_bytes(b"<gmd:MD_Metadata/>")
            response = Mock(status_code=201)
            response.json.return_value = {"testObject": {"id": "EIDsource"}}

            def post(url, *, files, timeout):
                self.assertEqual(url, "https://validator.test/v2/TestObjects?action=upload")
                self.assertEqual(timeout, inspire.INSPIRE_SERVER_TIMEOUT)
                filename, handle = files["fileupload"]
                self.assertEqual(filename, "metadata.xml")
                self.assertEqual(handle.read(), xml.read_bytes())
                return response

            with patch.object(inspire.requests, "post", side_effect=post):
                result = inspire.InspireServiceClient.create_test_object(xml)
            self.assertEqual(result, (201, "source", "ok"))

    def test_start_run_keeps_suite_and_object_in_service_payload(self):
        response = Mock()
        response.json.return_value = {"EtfItemCollection": {"testRuns": {"TestRun": {"id": "run"}}}}
        with patch.object(inspire.requests, "post", return_value=response) as post:
            self.assertEqual(inspire.InspireServiceClient.start_test_run("suite", "object"), ("run", "ok"))
        self.assertEqual(post.call_args.args, ("https://validator.test/v2/TestRuns",))
        self.assertEqual(post.call_args.kwargs["timeout"], inspire.INSPIRE_SERVER_TIMEOUT)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["executableTestSuiteIds"], ["suite"])
        self.assertEqual(payload["testObject"], {"id": "object"})
        self.assertEqual(payload["arguments"], {"files_to_test": ".*", "tests_to_execute": ".*"})

    def test_lightweight_validation_uses_original_command_and_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            xml = root / "metadata.xml"
            status = Mock()
            result = SimpleNamespace(stdout="[INVALID] Missing field", stderr="validator detail")
            with patch.object(inspire.subprocess, "run", return_value=result) as run:
                inspire.do_inspire_check(xml, "step", root, status, lightweight_validator=True)
            run.assert_called_once_with(
                ["geonetwork-validate", "--xml", str(xml)], capture_output=True, text=True,
            )
            self.assertEqual((root / "step_report.txt").read_text(), result.stdout + result.stderr)
            status.add_attachment.assert_called_once_with("step_report.txt")
            status.failed.assert_called_once()
            status.info.assert_not_called()


class QCFixtureLoggingTests(TestCase):
    def test_test_logging_cleanup_preserves_existing_handlers_and_level(self):
        from qc_tool.test.helper import init_logging

        root = logging.getLogger()
        handlers, level = list(root.handlers), root.level
        cleanup = init_logging()
        try:
            self.assertEqual(len(root.handlers), len(handlers) + 1)
        finally:
            cleanup()
        self.assertEqual(root.handlers, handlers)
        self.assertEqual(root.level, level)


class InspireClientImportTests(TestCase):
    def test_http_client_import_does_not_load_check_or_frontend_dependencies(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from qc_tool.worker.inspire import InspireServiceClient; "
                "blocked = ('osgeo', 'pypdf', 'qc_tool.vector', 'qc_tool.raster', 'qc_tool.frontend'); "
                "loaded = [name for name in sys.modules "
                "if any(name == prefix or name.startswith(prefix + '.') for prefix in blocked)]; "
                "assert not loaded, loaded",
            ],
            cwd=Path(__file__).resolve().parents[3],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
