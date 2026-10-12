"""Historical submitted names block new admissions without fabricating approval."""

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from qc_tool.frontend.accounts.services.api_tokens import issue_personal_access_token
from qc_tool.frontend.dashboard.models import Delivery, DeliverySubmission, S3Info
from qc_tool.frontend.dashboard.services.catalog import get_product_coverage
from qc_tool.frontend.dashboard.services.deliveries.history import (
    LegacyDeliveryAlreadySubmitted, require_available_legacy_filename,
)
from qc_tool.frontend.dashboard.services.s3 import S3Delivery
from qc_tool.frontend.dashboard.services.submissions import SubmissionError
from qc_tool.frontend.dashboard.services.submissions.reservation import reserve_submission
from qc_tool.frontend.dashboard.services.tests.test_submissions import SubmissionFixtureMixin
from qc_tool.frontend.dashboard.services.uploads.access import require_upload_filename
from qc_tool.frontend.dashboard.services.uploads.resumable import ResumableUploadError
from qc_tool.frontend.dashboard.tests.test_resumable_registration import UploadRegistrationFixture


class LegacyFilenameUploadTests(UploadRegistrationFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.other = get_user_model().objects.create_user(username="private-history-uploader")
        self.historical = Delivery.objects.create(
            user=self.other, filename="DELIVERY.ZIP", size_bytes=4,
            date_submitted=timezone.now(), is_deleted=True,
        )
        self.authorization = "Bearer " + issue_personal_access_token(self.user, "History test").raw_token

    def assert_collision(self, response):
        self.assertEqual(response.status_code, 409, response.content)
        payload = response.json()
        self.assertEqual(payload["code"], "legacy_delivery_already_submitted")
        self.assertNotIn(self.other.username, payload["message"])
        self.assertNotIn("delivery_id", payload)
        self.assertNotIn("files", payload)
        self.assertEqual(Delivery.objects.count(), 1)

    def test_browser_preflight_and_chunks_reject_cross_owner_deleted_history(self):
        self.assert_collision(self.client.post(
            reverse("delivery_upload_check"), {"filenames": ["delivery.zip"]},
            content_type="application/json",
        ))
        self.assert_collision(self.client.get(self.url, self.parameters))
        self.assert_collision(self.post_chunk())
        self.assertFalse(self.paths.target_path.exists())

    def test_local_api_rejects_history_before_creating_another_record(self):
        self.paths.user_root.mkdir(exist_ok=True)
        self.paths.target_path.write_bytes(b"abcd")
        self.assert_collision(self.client.post(
            reverse("api_register_delivery"),
            json.dumps({"uploaded_file": str(self.paths.target_path)}),
            content_type="application/json", HTTP_AUTHORIZATION=self.authorization,
        ))
        self.assertEqual(self.paths.target_path.read_bytes(), b"abcd")

    @override_settings(S3_ALLOWED_ENDPOINTS=("https://objects.example.com",))
    def test_s3_api_rejects_history_before_storing_credentials(self):
        with patch(
            "qc_tool.frontend.dashboard.views.api_access.deliveries.inspect_s3_delivery",
            return_value=S3Delivery(filename="incoming/delivery.zip", size_bytes=4),
        ), patch(
            "qc_tool.frontend.dashboard.views.api_access.deliveries.registration.s3.store_s3_credentials",
        ) as store:
            self.assert_collision(self.client.post(
                reverse("api_register_delivery_s3"), json.dumps({
                    "host": "https://objects.example.com", "access_key": "access",
                    "secret_key": "secret", "bucketname": "deliveries",
                    "key_prefix": "incoming/delivery.zip",
                }), content_type="application/json", HTTP_AUTHORIZATION=self.authorization,
            ))
        store.assert_not_called()
        self.assertFalse(S3Info.objects.exists())

    def test_nonsubmitted_other_owner_history_does_not_block_upload(self):
        self.historical.date_submitted = None
        self.historical.save(update_fields=("date_submitted",))
        self.assertEqual(self.post_chunk().status_code, 200)
        self.assertEqual(Delivery.objects.count(), 2)

    def test_product_authorization_precedes_history_lookup(self):
        from qc_tool.frontend.accounts.authorization import access_for
        self.user.product_grants.all().delete()
        with patch(
            "qc_tool.frontend.dashboard.services.uploads.access.require_available_legacy_filename",
        ) as lookup:
            with self.assertRaises(ResumableUploadError) as denied:
                require_upload_filename(access_for(self.user), "delivery.zip")
        self.assertEqual(denied.exception.status_code, 403)
        lookup.assert_not_called()

    def test_renamed_filename_remains_outside_the_historical_guard(self):
        require_available_legacy_filename("delivery_new_version.zip")
        with self.assertRaises(LegacyDeliveryAlreadySubmitted):
            require_available_legacy_filename("delivery.zip")
        require_available_legacy_filename("delivery.zip", exclude_delivery_id=self.historical.pk)


class LegacyFilenameSubmissionTests(SubmissionFixtureMixin, TestCase):
    def create_history(self, *, submitted=True):
        return Delivery.objects.create(
            filename="DELIVERY.ZIP", size_bytes=4, is_deleted=True,
            date_submitted=timezone.now() if submitted else None,
        )

    def reserve(self, user, delivery, channel):
        return reserve_submission(
            delivery_id=delivery.pk, actor=user, account_access=self.owner_access(user),
            request_channel=channel, api_token=None,
        )

    def test_browser_and_api_reservations_reject_already_created_matching_uploads(self):
        self.create_history()
        user, delivery, _job, _root = self.create_candidate("fresh-upload")
        for channel in ("browser", "api"):
            with self.subTest(channel=channel), self.assertRaises(SubmissionError) as denied:
                self.reserve(user, delivery, channel)
            self.assertEqual(denied.exception.status_code, 409)
            self.assertEqual(denied.exception.code, "legacy_delivery_already_submitted")
        self.assertFalse(DeliverySubmission.objects.exists())
        self.assertFalse(self.submission_root.exists())
        coverage = get_product_coverage(self.release)
        self.assertEqual((coverage.accepted, coverage.remaining), (0, 1))

    def test_nonsubmitted_history_does_not_block_reservation(self):
        self.create_history(submitted=False)
        user, delivery, _job, _root = self.create_candidate("not-submitted-history")
        self.assertFalse(self.reserve(user, delivery, "browser").already_existed)

    def test_current_receipts_are_excluded_including_declined_corrections(self):
        user, delivery, _job, job_root = self.create_candidate("current-receipt")
        self.submit(user, delivery, job_root)
        submission = DeliverySubmission.objects.get()
        self.review(submission, user, decision="declined", notes="Upload the corrected package.")
        require_available_legacy_filename("delivery.zip")
        require_upload_filename(self.owner_access(user), "delivery.zip")
        self.assertEqual(get_product_coverage(self.release).accepted, 0)

    def test_existing_current_submission_retry_precedes_later_legacy_collision(self):
        user, delivery, _job, job_root = self.create_candidate("current-retry")
        self.submit(user, delivery, job_root)
        self.create_history()
        result = self.submit(user, delivery, job_root)
        self.assertTrue(result.idempotent)
        self.assertEqual(DeliverySubmission.objects.count(), 1)

    def test_submission_product_authorization_precedes_history_lookup(self):
        self.create_history()
        user, delivery, _job, _root = self.create_candidate("revoked-submission")
        user.product_grants.all().delete()
        with patch(
            "qc_tool.frontend.dashboard.services.submissions.reservation.service.require_available_legacy_filename",
        ) as lookup:
            with self.assertRaises(SubmissionError) as denied:
                self.reserve(user, delivery, "browser")
        self.assertEqual(denied.exception.status_code, 403)
        lookup.assert_not_called()
