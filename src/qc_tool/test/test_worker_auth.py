from unittest import TestCase
from unittest.mock import Mock
from unittest.mock import patch
from uuid import UUID

from qc_tool.common import check_running_job
from qc_tool.common import JOB_ERROR
from qc_tool.common import JOB_LOST
from qc_tool.worker_auth import build_worker_authorization
from qc_tool.worker_auth import InvalidWorkerUrl
from qc_tool.worker_auth import parse_worker_authorization
from qc_tool.worker_auth import worker_job_status_url
from qc_tool.worker_auth import worker_origin_from_remote_address


JOB_UUID = UUID("00000000-0000-0000-0000-000000000001")


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.read = Mock(return_value=payload)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


class WorkerHeaderTests(TestCase):
    def test_round_trips_one_strict_machine_credential(self):
        header = build_worker_authorization("private-token")

        self.assertEqual(header, "WorkerToken private-token")
        self.assertEqual(
            parse_worker_authorization(header),
            "private-token",
        )

    def test_rejects_ambiguous_or_non_ascii_headers(self):
        for value in (
            None,
            "Bearer token",
            "WorkerToken",
            "WorkerToken one two",
            "WorkerToken\ttoken",
            "WorkerToken nön-ascii",
        ):
            with self.subTest(value=value):
                self.assertIsNone(parse_worker_authorization(value))


class WorkerUrlTests(TestCase):
    def test_builds_only_fixed_port_ip_origins(self):
        origin = worker_origin_from_remote_address("2001:db8::1", 8000)

        self.assertEqual(origin, "http://[2001:db8::1]:8000/")
        self.assertEqual(
            worker_job_status_url(origin, JOB_UUID, expected_port=8000),
            "http://[2001:db8::1]:8000/jobs/{}.json".format(JOB_UUID),
        )

    def test_rejects_hostnames_credentials_paths_and_port_changes(self):
        invalid_urls = (
            "http://worker.internal:8000/",
            "http://user:pass@127.0.0.1:8000/",
            "http://127.0.0.1:9000/",
            "http://127.0.0.1:8000/redirect",
        )

        for url in invalid_urls:
            with self.subTest(url=url):
                with self.assertRaises(InvalidWorkerUrl):
                    worker_job_status_url(url, JOB_UUID, expected_port=8000)


class WorkerStatusRequestTests(TestCase):
    @patch("qc_tool.common.get_worker_token", return_value="private-token")
    @patch("qc_tool.common._worker_status_opener.open")
    def test_uses_a_bounded_authenticated_status_request(self, open_url, _token):
        response = FakeResponse(b'{"uuid": "job"}')
        open_url.return_value = response

        result = check_running_job(
            str(JOB_UUID),
            "http://127.0.0.1:8000/",
            2,
        )

        self.assertIsNone(result)
        request = open_url.call_args.args[0]
        self.assertEqual(
            request.get_header("Authorization"),
            "WorkerToken private-token",
        )
        self.assertEqual(
            request.full_url,
            "http://127.0.0.1:8000/jobs/{}.json".format(JOB_UUID),
        )
        response.read.assert_called_once_with(8193)

    @patch("qc_tool.common.load_job_status", return_value=JOB_ERROR)
    @patch("qc_tool.common._worker_status_opener.open")
    def test_rejects_an_untrusted_worker_url_before_network_io(
        self,
        open_url,
        _load_status,
    ):
        result = check_running_job(
            str(JOB_UUID),
            "http://metadata.internal:8000/",
            2,
        )

        self.assertEqual(result, JOB_LOST)
        open_url.assert_not_called()
