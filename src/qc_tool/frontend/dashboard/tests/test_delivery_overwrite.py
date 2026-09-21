"""Owned replacements retain history and recover without trusting new filenames."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import close_old_connections
from django.test import TransactionTestCase
from qc_tool.frontend.dashboard.services.uploads import ResumableUploadError
from qc_tool.frontend.dashboard.services.uploads.registration import receive_registered_chunk
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile

from qc_tool.common import JOB_OK, JOB_WAITING
from qc_tool.frontend.dashboard.models import Delivery, Job, DeliverySubmission, Product, ProductRelease, ProductUnit
from qc_tool.frontend.dashboard.services.uploads import ResumableUploadDescriptor, prepare_resumable_paths
from qc_tool.frontend.dashboard.tests.test_resumable_registration import UploadRegistrationFixture


class DeliveryOverwriteTests(UploadRegistrationFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.post_chunk().status_code, 200)
        self.original = Delivery.objects.get()
        self.job = Job.objects.create(delivery=self.original, job_status=JOB_OK, product_ident="example", product_description="Example")
        self.parameters = {**self.parameters, "resumableIdentifier": "replacement", "overwrite_delivery_id": str(self.original.pk)}
        self.descriptor = ResumableUploadDescriptor.from_mapping(self.parameters)
        self.paths = prepare_resumable_paths(self.descriptor, media_root=self.media_root, username=self.user.username)

    def replace(self, data=b"new!", **parameters):
        return self.client.post(self.url, {**self.parameters, **parameters, "file": SimpleUploadedFile("chunk", data)})

    def assert_original_intact(self):
        self.original.refresh_from_db()
        self.assertFalse(self.original.is_deleted)
        self.assertEqual(self.paths.target_path.read_bytes(), b"abcd")
        self.assertEqual(Job.objects.get(pk=self.job.pk).delivery_id, self.original.pk)

    def test_replacement_creates_fresh_identity_and_retains_original_archive_and_qc(self):
        response = self.replace()
        self.assertEqual(response.status_code, 200, response.content)
        replacement = Delivery.objects.get(is_deleted=False)
        self.assertNotEqual(replacement.pk, self.original.pk)
        self.original.refresh_from_db()
        self.assertTrue(self.original.is_deleted)
        self.assertEqual(self.paths.target_path.read_bytes(), b"new!")
        self.assertEqual((self.paths.chunks_dir / ".previous").read_bytes(), b"abcd")
        self.assertEqual(Job.objects.get(pk=self.job.pk).delivery_id, self.original.pk)
        self.assertFalse(Job.objects.filter(delivery=replacement).exists())
        self.assertIsNone(replacement.verified_product_unit_code)
        self.assertEqual(self.client.get(self.url, self.parameters).status_code, 200)
        self.assertEqual(self.replace().json()["delivery_id"], replacement.pk)
        self.assertEqual(Delivery.objects.count(), 2)

    def test_partial_or_invalid_replacement_never_changes_original(self):
        parameters = {"resumableTotalSize": "10", "resumableTotalChunks": "2", "resumableCurrentChunkSize": "5"}
        self.assertEqual(self.replace(b"newer", **parameters).status_code, 200)
        self.assert_original_intact()
        self.assertEqual(self.replace(b"too long").status_code, 400)
        self.assert_original_intact()

    def test_owner_and_expected_identity_are_rechecked(self):
        other = get_user_model().objects.create_superuser(username="other-owner", email="other@example.test", password="unused")
        self.client.force_login(other)
        response = self.replace()
        self.assertEqual(response.status_code, 409)
        self.assert_original_intact()
        self.client.force_login(self.user)
        self.original.is_deleted = True
        self.original.save(update_fields=("is_deleted",))
        newer = Delivery.objects.create(user=self.user, filename=self.original.filename, size_bytes=4)
        self.assertEqual(self.replace().json()["code"], "overwrite_target_changed")
        self.assertEqual(Delivery.objects.get(is_deleted=False).pk, newer.pk)
        self.assertEqual(self.paths.target_path.read_bytes(), b"abcd")

    def test_active_qc_and_legacy_submission_are_protected(self):
        self.job.job_status = JOB_WAITING
        self.job.save(update_fields=("job_status",))
        self.assertEqual(self.replace().json()["code"], "overwrite_not_allowed")
        self.assert_original_intact()
        self.job.job_status = JOB_OK
        self.job.save(update_fields=("job_status",))
        self.original.date_submitted = timezone.now()
        self.original.save(update_fields=("date_submitted",))
        self.assertEqual(self.replace().json()["code"], "overwrite_not_allowed")
        self.assert_original_intact()

    def test_submission_reservation_blocks_overwrite_even_before_legacy_timestamp(self):
        product = Product.objects.create(ident="overwrite-retained", name="Overwrite retained")
        release = ProductRelease.objects.create(product=product, release_key="2026", revision=1, catalog_digest="a" * 64, description="Retained")
        aoi = ProductUnit.objects.create(product_release=release, product_unit_code="CZ")
        DeliverySubmission.objects.create(delivery=self.original, job=self.job, product_release=release, product_unit=aoi,
                                          product_unit_code="CZ", verified_product_unit_code="CZ", submitted_by_username=self.user.username,
                                          request_channel="browser")
        self.assertEqual(self.replace().json()["code"], "overwrite_not_allowed")
        self.assert_original_intact()

    def test_failure_before_retirement_preserves_original_and_allows_retry(self):
        with patch("qc_tool.frontend.dashboard.services.uploads.overwrite._write_journal", side_effect=OSError("disk full")):
            self.assertEqual(self.replace().status_code, 503)
        self.assert_original_intact()
        self.assertEqual(self.replace().status_code, 200)

    def test_failed_swap_restores_active_original_and_retry_reuses_successor(self):
        real_replace = os.replace
        def fail_publication(source, destination, **kwargs):
            if source == ".publishing":
                raise OSError("publication unavailable")
            return real_replace(source, destination, **kwargs)
        with patch("qc_tool.frontend.dashboard.services.uploads.overwrite.os.replace", side_effect=fail_publication):
            self.assertEqual(self.replace().status_code, 503)
        self.assert_original_intact()
        self.assertEqual(Delivery.objects.count(), 2)
        self.assertEqual(self.replace().status_code, 200)
        self.assertEqual(Delivery.objects.count(), 2)

    def test_process_interruption_after_swap_is_fail_closed_and_retry_recovers(self):
        class Interrupted(BaseException):
            pass
        real_replace = os.replace
        def interrupted(source, destination, **kwargs):
            result = real_replace(source, destination, **kwargs)
            if source == ".publishing":
                raise Interrupted()
            return result
        with patch("qc_tool.frontend.dashboard.services.uploads.overwrite.os.replace", side_effect=interrupted):
            with self.assertRaises(Interrupted):
                self.replace()
        self.original.refresh_from_db()
        self.assertTrue(self.original.is_deleted)
        self.assertFalse(Delivery.objects.filter(is_deleted=False).exists())
        self.assertEqual((self.paths.chunks_dir / ".previous").read_bytes(), b"abcd")
        self.assertEqual(self.replace().status_code, 200)
        self.assertEqual(Delivery.objects.count(), 2)

    def test_receipt_failure_never_rolls_back_a_committed_successor(self):
        with patch("qc_tool.frontend.dashboard.services.uploads.registration._write_receipt", side_effect=OSError("receipt unavailable")):
            self.assertEqual(self.replace().status_code, 503)
        successor = Delivery.objects.get(is_deleted=False)
        self.assertNotEqual(successor.pk, self.original.pk)
        self.assertEqual(self.paths.target_path.read_bytes(), b"new!")
        self.assertEqual(self.replace().json()["delivery_id"], successor.pk)
        self.assertEqual(Delivery.objects.count(), 2)

    def test_operator_recovery_inspects_then_finishes_without_browser_state(self):
        from io import StringIO
        from django.core.management import call_command
        with patch("qc_tool.frontend.dashboard.services.uploads.registration._write_receipt", side_effect=OSError("receipt unavailable")):
            self.assertEqual(self.replace().status_code, 503)
        successor = Delivery.objects.get(is_deleted=False)
        output = StringIO()
        call_command("recover_delivery_overwrite", delivery_id=self.original.pk, upload_key=self.descriptor.storage_key, stdout=output)
        self.assertIn("Inspection only", output.getvalue())
        self.assertFalse((self.paths.chunks_dir / ".registered").exists())
        call_command("recover_delivery_overwrite", delivery_id=self.original.pk, upload_key=self.descriptor.storage_key, apply=True, stdout=output)
        self.assertTrue((self.paths.chunks_dir / ".registered").exists())
        self.assertEqual(Delivery.objects.get(is_deleted=False).pk, successor.pk)



class ConcurrentDeliveryOverwriteTests(UploadRegistrationFixture, TransactionTestCase):
    def test_two_explicit_replacements_cannot_both_replace_the_same_original(self):
        self.assertEqual(self.post_chunk().status_code, 200)
        original = Delivery.objects.get()
        candidates = []
        for number in range(2):
            descriptor = ResumableUploadDescriptor.from_mapping({
                **self.parameters, "resumableIdentifier": f"concurrent-overwrite-{number}",
                "overwrite_delivery_id": str(original.pk),
            })
            paths = prepare_resumable_paths(descriptor, media_root=self.media_root, username=self.user.username)
            candidates.append((descriptor, paths, b"newA" if number == 0 else b"newB"))
        barrier = Barrier(2)
        def send(candidate):
            close_old_connections()
            descriptor, paths, data = candidate
            try:
                barrier.wait(timeout=10)
                result = receive_registered_chunk(descriptor, paths, user=self.user, uploaded_chunk=SimpleUploadedFile("chunk", data))
                return ("ok", result.pk, data)
            except ResumableUploadError as exc:
                return (exc.code, None, data)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(send, candidates))
        self.assertCountEqual([result[0] for result in outcomes], ["ok", "overwrite_target_changed"])
        winner = next(result for result in outcomes if result[0] == "ok")
        self.assertEqual(Delivery.objects.get(is_deleted=False).pk, winner[1])
        self.assertEqual(self.paths.target_path.read_bytes(), winner[2])
        self.assertEqual(Delivery.objects.count(), 2)
