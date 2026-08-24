from io import BytesIO
from unittest import TestCase
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults

from qc_tool.worker import scheduler


def request_worker(path, *, authorization=None, method="GET", body=b""):
    environment = {}
    setup_testing_defaults(environment)
    environment.update(
        {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "CONTENT_LENGTH": str(len(body)),
            "wsgi.input": BytesIO(body),
        }
    )
    if authorization is not None:
        environment["HTTP_AUTHORIZATION"] = authorization
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = status
        captured["headers"] = dict(headers)

    captured["body"] = b"".join(
        scheduler.bottle.default_app()(environment, start_response)
    )
    return captured


class WorkerServiceAuthenticationTests(TestCase):
    def test_health_is_public_but_contains_no_job_state(self):
        response = request_worker("/health")

        self.assertTrue(response["status"].startswith("200 "))
        self.assertEqual(response["body"], b'{"status": "ok"}')

    @patch("qc_tool.worker.scheduler.auth_worker")
    def test_job_state_rejects_missing_credentials_before_authentication(self, auth):
        response = request_worker("/table.json")

        self.assertTrue(response["status"].startswith("401 "))
        self.assertEqual(
            {
                key.casefold(): value
                for key, value in response["headers"].items()
            }["www-authenticate"],
            'WorkerToken realm="QC Tool Worker"',
        )
        self.assertEqual(response["body"], b"")
        auth.assert_not_called()

    @patch("qc_tool.worker.scheduler.auth_worker", return_value=True)
    def test_valid_machine_header_allows_job_state(self, auth):
        response = request_worker(
            "/table.json",
            authorization="WorkerToken valid-token",
        )

        self.assertTrue(response["status"].startswith("200 "))
        self.assertEqual(response["body"], b"[]")
        auth.assert_called_once_with("valid-token")

    @patch("qc_tool.worker.scheduler.auth_worker", return_value=True)
    def test_slot_mutation_is_bounded_even_for_an_authenticated_worker(self, auth):
        response = request_worker(
            "/max_slots",
            authorization="WorkerToken valid-token",
            method="PUT",
            body=b"1000000",
        )

        self.assertTrue(response["status"].startswith("400 "))
        auth.assert_called_once_with("valid-token")
