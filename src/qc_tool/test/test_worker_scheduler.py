from unittest import TestCase
from io import BytesIO
from subprocess import PIPE
from unittest.mock import MagicMock
from unittest.mock import mock_open
from unittest.mock import patch

from qc_tool.worker.cmd import read_s3_secret
from qc_tool.worker.scheduler import JobController
from qc_tool.worker.scheduler import Scheduler


class SchedulerPullJobTests(TestCase):
    @patch("qc_tool.worker.scheduler._worker_url_opener.open")
    @patch(
        "qc_tool.worker.scheduler.get_worker_token",
        return_value="worker-secret",
    )
    def test_pull_uses_post_and_authorization_header(
        self,
        _get_worker_token,
        open_worker_url,
    ):
        payload = (
            b'{"job_uuid":"00000000-0000-0000-0000-000000000001",'
            b'"product_ident":"product","username":"alice",'
            b'"filename":"delivery.zip","skip_steps":null,'
            b'"s3_host":"https://objects.example.test",'
            b'"s3_access_key":"access-id",'
            b'"s3_secret_key":"do-not-log",'
            b'"s3_bucketname":"deliveries",'
            b'"s3_key_prefix":"incoming/delivery"}'
        )
        response = open_worker_url.return_value.__enter__.return_value
        response.read.return_value = payload
        response.headers = {}

        result = Scheduler(
            "https://frontend.example.test/pull_job"
        ).pull_job()

        request = open_worker_url.call_args.args[0]
        self.assertEqual(open_worker_url.call_args.kwargs["timeout"], 30)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(
            request.get_header("Authorization"),
            "WorkerToken worker-secret",
        )
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertEqual(
            request.full_url,
            "https://frontend.example.test/pull_job",
        )
        self.assertNotIn("worker-secret", request.full_url)
        self.assertEqual(result["s3_secret_key"], "do-not-log")
        self.assertEqual(result["username"], "alice")


class JobControllerCredentialTests(TestCase):
    def setUp(self):
        self.job_args = {
            "job_uuid": "job-1",
            "product_ident": "product",
            "skip_steps": None,
            "username": "alice",
            "filename": "delivery.zip",
            "s3_host": "https://objects.example.test",
            "s3_access_key": "access-id",
            "s3_secret_key": "do-not-expose",
            "s3_bucketname": "deliveries",
            "s3_key_prefix": "incoming/delivery",
        }

    @patch("qc_tool.worker.scheduler.job_table.rm")
    @patch("qc_tool.worker.scheduler.job_table.put")
    @patch("qc_tool.worker.scheduler.open", mock_open())
    @patch("qc_tool.worker.scheduler.Popen")
    def test_s3_secret_is_piped_and_never_placed_in_argv(
        self,
        popen,
        _put,
        _remove,
    ):
        process = MagicMock(pid=123, returncode=0)
        popen.return_value = process

        JobController(self.job_args).run(MagicMock())

        args = popen.call_args.kwargs["args"]
        self.assertIn("--s3-secret-key-stdin", args)
        self.assertNotIn("--s3-secret-key", args)
        self.assertNotIn("do-not-expose", args)
        self.assertEqual(popen.call_args.kwargs["stdin"], PIPE)
        process.communicate.assert_called_once_with(input=b"do-not-expose")


class WorkerCommandSecretTests(TestCase):
    def test_reads_bounded_secret_from_private_pipe(self):
        self.assertEqual(
            read_s3_secret(BytesIO(b"private-secret")),
            "private-secret",
        )

    def test_rejects_empty_and_oversized_secrets(self):
        with self.assertRaises(ValueError):
            read_s3_secret(BytesIO(b""))
        with self.assertRaises(ValueError):
            read_s3_secret(BytesIO(b"x" * 4097))
