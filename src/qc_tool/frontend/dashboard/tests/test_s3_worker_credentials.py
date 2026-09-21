import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings

from qc_tool.common import JOB_ERROR, JOB_RUNNING, JOB_WAITING
from qc_tool.frontend.dashboard.models import Delivery, Job, S3Info
from qc_tool.frontend.dashboard.services.product_units.jobs.creation import create_delivery_job
from qc_tool.frontend.dashboard.services.s3 import S3Registration
from qc_tool.frontend.dashboard.services.s3.credentials import store_s3_credentials
from qc_tool.frontend.dashboard.views.workers import pull_job


class S3WorkerCredentialsTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Path(directory.name) / "credentials"
        self.enterContext(override_settings(S3_CREDENTIALS_DIR=self.store))
        registration = S3Registration(
            endpoint="https://objects.example.test", access_key="test-access-key",
            secret_key="test-private-secret", bucket_name="deliveries", key_prefix="incoming/a.zip",
        )
        reference = store_s3_credentials(registration)
        self.source = S3Info.objects.create(
            host=registration.endpoint, credential_ref=reference,
            bucketname=registration.bucket_name, key_prefix=registration.key_prefix,
        )
        self.user = get_user_model().objects.create_user(username="s3-worker-owner")
        self.delivery = Delivery.objects.create(
            user=self.user, filename="a.zip", size_bytes=42, s3=self.source,
        )
        self.request = RequestFactory().get("/workers/pull/", REMOTE_ADDR="127.0.0.1")

    def job(self):
        return Job.objects.create(
            delivery=self.delivery, product_ident="product", product_description="Product",
            job_status=JOB_WAITING,
        )

    def test_dispatch_resolves_credentials_without_storing_them_in_database(self):
        job = self.job()
        response = pull_job(self.request)
        payload = json.loads(response.content)
        self.assertEqual(payload["s3_access_key"], "test-access-key")
        self.assertEqual(payload["s3_secret_key"], "test-private-secret")
        self.assertEqual(payload["s3_key_prefix"], self.source.key_prefix)
        job.refresh_from_db()
        self.assertEqual(job.job_status, JOB_RUNNING)
        self.assertFalse(hasattr(self.source, "access_key"))
        self.assertFalse(hasattr(self.source, "secret_key"))

    def test_dispatch_finishes_job_safely_if_secret_disappears(self):
        failed = self.job()
        (self.store / (self.source.credential_ref + ".json")).unlink()
        with self.assertLogs("qc_tool.frontend.dashboard.views.workers", level="WARNING") as logs:
            response = pull_job(self.request)
        self.assertIsNone(json.loads(response.content))
        self.assertNotIn("test-private-secret", str(logs.output))
        failed.refresh_from_db()
        self.assertEqual(failed.job_status, JOB_ERROR)
        self.assertIsNotNone(failed.date_finished)

    @patch("qc_tool.frontend.dashboard.services.product_units.jobs.creation._catalog_snapshot")
    def test_imported_source_without_reference_cannot_queue_a_job(self, snapshot):
        self.source.credential_ref = ""
        self.source.save(update_fields=["credential_ref"])
        with self.assertRaisesMessage(ValueError, "S3 credentials are unavailable"):
            create_delivery_job(
                self.delivery, product_ident="product", product_description="Product",
                skip_steps=None, logger=logging.getLogger(__name__),
            )
        snapshot.assert_not_called()
        self.assertFalse(Job.objects.exists())
