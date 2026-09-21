"""Job history belongs to a delivery and survives every refused deletion."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from qc_tool.common import JOB_FAILED
from qc_tool.common import JOB_OK
from qc_tool.common import JOB_RUNNING
from qc_tool.common import JOB_WAITING
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import DeliverySubmission
from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.dashboard.models import Product
from qc_tool.frontend.dashboard.models import ProductUnit
from qc_tool.frontend.dashboard.models import ProductRelease
from qc_tool.frontend.dashboard.services.uploads import DeliveryUploadPathError


class DeliveryDeletionTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.media_root = Path(directory.name)
        settings = override_settings(MEDIA_ROOT=self.media_root)
        settings.enable()
        self.addCleanup(settings.disable)
        self.owner = get_user_model().objects.create_user(username="owner")
        UserProductGrant.objects.create(user=self.owner, product_ident="test-product")
        self.other = get_user_model().objects.create_user(username="other")
        self.delivery = self.create_delivery(self.owner)
        self.jobs = [
            Job.objects.create(delivery=self.delivery, job_status=status)
            for status in (JOB_FAILED, JOB_OK)
        ]
        self.client.force_login(self.owner)

    def create_delivery(self, user, filename="delivery.zip"):
        delivery = Delivery.objects.create(
            user=user, filename=filename, size_bytes=4, product_ident="test-product",
        )
        path = self.upload_path(delivery)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"data")
        return delivery

    def upload_path(self, delivery):
        return self.media_root / delivery.user.username / delivery.filename

    def delete(self, *deliveries):
        return self.client.post(
            reverse("delivery_delete"),
            {"ids": ",".join(str(delivery.pk) for delivery in deliveries)},
        )

    def assert_history_intact(self):
        self.delivery.refresh_from_db()
        self.assertFalse(self.delivery.is_deleted)
        self.assertEqual(self.upload_path(self.delivery).read_bytes(), b"data")
        self.assertCountEqual(
            Job.objects.filter(delivery=self.delivery).values_list("pk", flat=True),
            [job.pk for job in self.jobs],
        )

    def test_delivery_deletion_removes_only_selected_deliveries_job_history(self):
        selected = self.create_delivery(self.owner, "second.zip")
        Job.objects.create(delivery=selected, job_status=JOB_OK)
        other = self.create_delivery(self.other)
        other_job = Job.objects.create(delivery=other, job_status=JOB_OK)
        previous = Delivery.objects.create(
            user=self.owner, filename=self.delivery.filename,
            size_bytes=4, is_deleted=True,
        )
        previous_job = Job.objects.create(delivery=previous, job_status=JOB_OK)

        response = self.delete(self.delivery, selected)

        self.assertEqual(response.status_code, 200, response.content)
        for delivery in (self.delivery, selected):
            delivery.refresh_from_db()
            self.assertTrue(delivery.is_deleted)
            self.assertFalse(self.upload_path(delivery).exists())
            self.assertFalse(Job.objects.filter(delivery=delivery).exists())
        self.assertEqual(self.upload_path(other).read_bytes(), b"data")
        self.assertCountEqual(
            Job.objects.values_list("pk", flat=True),
            [other_job.pk, previous_job.pk],
        )

    def test_any_active_job_preserves_the_delivery_and_all_history(self):
        for status in (JOB_WAITING, JOB_RUNNING):
            with self.subTest(status=status):
                # An older active job must still block deletion even when the
                # latest job has already finished.
                Job.objects.filter(pk=self.jobs[0].pk).update(job_status=status)
                response = self.delete(self.delivery)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()["code"], "delivery_has_active_job")
                self.assert_history_intact()

    def test_late_status_refresh_after_deletion_is_a_safe_no_op(self):
        stale_job = self.jobs[0]
        # A poll loaded this state before another poll completed the job.
        stale_job.job_status = JOB_RUNNING
        self.assertEqual(self.delete(self.delivery).status_code, 200)

        stale_job.update_status(JOB_FAILED)

        self.delivery.refresh_from_db()
        self.assertTrue(self.delivery.is_deleted)
        self.assertFalse(Job.objects.filter(delivery=self.delivery).exists())

    def test_submission_timestamp_preserves_delivery_and_job_history(self):
        self.delivery.date_submitted = timezone.now()
        self.delivery.save(update_fields=("date_submitted",))

        response = self.delete(self.delivery)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "delivery_has_submission")
        self.assert_history_intact()

    def test_submission_receipt_protects_history_before_timestamp_is_written(self):
        product = Product.objects.create(ident="retained", name="Retained")
        release = ProductRelease.objects.create(
            product=product, release_key="2026", revision=1,
            catalog_digest="a" * 64, description="Retained",
        )
        aoi = ProductUnit.objects.create(product_release=release, product_unit_code="CZ")
        submission = DeliverySubmission.objects.create(
            delivery=self.delivery, job=self.jobs[-1], product_release=release,
            product_unit=aoi, product_unit_code="CZ", verified_product_unit_code="CZ",
            submitted_by_username=self.owner.username, request_channel="browser",
        )

        response = self.delete(self.delivery)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "delivery_has_submission")
        self.assert_history_intact()
        self.assertTrue(DeliverySubmission.objects.filter(pk=submission.pk).exists())

    def test_foreign_delivery_in_batch_prevents_all_deletions(self):
        other = self.create_delivery(self.other)
        other_job = Job.objects.create(delivery=other, job_status=JOB_OK)

        response = self.delete(self.delivery, other)

        self.assertEqual(response.status_code, 403)
        self.assert_history_intact()
        self.assertTrue(Job.objects.filter(pk=other_job.pk).exists())
        self.assertEqual(self.upload_path(other).read_bytes(), b"data")

    def test_revoked_product_assignment_preserves_delivery_and_job_history(self):
        self.owner.product_grants.all().delete()

        response = self.delete(self.delivery)

        self.assertEqual(response.status_code, 403)
        self.assert_history_intact()

    def test_storage_failure_preserves_delivery_and_job_records(self):
        with patch(
            "qc_tool.frontend.dashboard.views.deliveries.actions.deletion."
            "remove_user_delivery_upload",
            side_effect=DeliveryUploadPathError(
                "unsafe_delivery_delete", "Cannot delete file safely.", 409,
            ),
        ):
            response = self.delete(self.delivery)

        self.assertEqual(response.status_code, 409)
        self.assert_history_intact()

    def test_superuser_cannot_delete_job_through_django_admin(self):
        superuser = get_user_model().objects.create_superuser(
            username="administrator", email="admin@example.test", password="unused",
        )
        self.client.force_login(superuser)
        delete_url = reverse("admin:dashboard_job_delete", args=(self.jobs[0].pk,))

        self.assertEqual(self.client.get(delete_url).status_code, 403)
        self.assertEqual(self.client.post(delete_url, {"post": "yes"}).status_code, 403)
        self.assert_history_intact()
