"""A resumed upload succeeds only when its live delivery exists."""

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.services.tests.test_resumable_uploads import _descriptor, _parameters
from qc_tool.frontend.dashboard.services.uploads import prepare_resumable_paths, store_chunk
from qc_tool.frontend.dashboard.services.uploads.registration import receive_registered_chunk


class UploadRegistrationFixture:
    def setUp(self):
        super().setUp()
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.media_root = Path(self.temporary.name)
        settings = override_settings(MEDIA_ROOT=self.media_root, MAINTENANCE_MODE=False)
        settings.enable()
        self.addCleanup(settings.disable)
        self.user = get_user_model().objects.create_user(username="resumable-owner")
        UserProductGrant.objects.create(user=self.user, product_ident="example")
        self.client.force_login(self.user)
        self.url = reverse("resumable_upload")
        self.parameters = _parameters()
        self.descriptor = _descriptor()
        self.paths = prepare_resumable_paths(self.descriptor, media_root=self.media_root, username=self.user.username)

    def post_chunk(self):
        return self.client.post(self.url, {**self.parameters, "file": SimpleUploadedFile("chunk", b"abcd")})


class ResumableRegistrationTests(UploadRegistrationFixture, TestCase):
    def test_complete_staging_requires_post_to_register_a_delivery(self):
        store_chunk(SimpleUploadedFile("chunk", b"abcd"), self.paths.chunk_path, expected_bytes=4)
        response = self.client.get(self.url, self.parameters)
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Delivery.objects.exists())
        response = self.post_chunk()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["delivery_id"], Delivery.objects.get().pk)
        self.assertEqual(self.paths.target_path.read_bytes(), b"abcd")

    def test_deleted_delivery_can_be_uploaded_again_with_same_identifier(self):
        self.assertEqual(self.post_chunk().status_code, 200)
        original = Delivery.objects.get()
        original.is_deleted = True
        original.save(update_fields=("is_deleted",))
        self.paths.target_path.unlink()
        # Simulate a stale chunk left by an interrupted old cleanup.
        self.paths.chunk_path.write_bytes(b"old!")
        self.assertEqual(self.client.get(self.url, self.parameters).status_code, 404)

        response = self.post_chunk()

        self.assertEqual(response.status_code, 200)
        current = Delivery.objects.get(is_deleted=False)
        self.assertNotEqual(current.pk, original.pk)
        self.assertEqual(self.paths.target_path.read_bytes(), b"abcd")
        self.assertEqual(Delivery.objects.count(), 2)

    def test_legacy_deleted_delivery_and_complete_stale_chunks_cannot_fake_success(self):
        Delivery.objects.create(user=self.user, filename="delivery.zip", size_bytes=4, is_deleted=True)
        self.paths.chunk_path.write_bytes(b"abcd")
        self.assertEqual(self.client.get(self.url, self.parameters).status_code, 404)
        self.assertEqual(self.post_chunk().status_code, 200)
        self.assertEqual(Delivery.objects.filter(is_deleted=False).count(), 1)

    def test_failed_registration_reuses_owned_file_and_creates_one_delivery(self):
        with patch("qc_tool.frontend.dashboard.services.uploads.registration.Delivery.objects.create", side_effect=RuntimeError("database temporarily unavailable")):
            failed = self.post_chunk()
        self.assertEqual(failed.status_code, 500)
        self.assertEqual(failed.json()["code"], "delivery_registration_failed")
        self.assertEqual(self.paths.target_path.read_bytes(), b"abcd")
        self.assertFalse(Delivery.objects.exists())
        self.assertEqual(self.client.get(self.url, self.parameters).status_code, 404)
        self.assertEqual(self.post_chunk().status_code, 200)
        self.assertEqual(Delivery.objects.count(), 1)
        self.assertFalse((self.paths.chunks_dir / ".assembled").exists())

    def test_registration_commit_before_receipt_is_recovered_idempotently(self):
        with patch("qc_tool.frontend.dashboard.services.uploads.registration._write_receipt", side_effect=OSError("interrupted receipt")):
            failed = self.post_chunk()
        self.assertEqual(failed.status_code, 503)
        self.assertEqual(failed.json()["code"], "upload_confirmation_failed")
        registered = Delivery.objects.get()
        self.assertEqual(self.client.get(self.url, self.parameters).status_code, 404)
        resumed = self.post_chunk()
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(resumed.json()["delivery_id"], registered.pk)
        self.assertEqual(Delivery.objects.count(), 1)

    def test_recovery_cannot_adopt_an_unrelated_same_name_record(self):
        with patch("qc_tool.frontend.dashboard.services.uploads.registration._write_receipt", side_effect=OSError("interrupted receipt")):
            self.assertEqual(self.post_chunk().status_code, 503)
        original = Delivery.objects.get()
        original.is_deleted = True
        original.save(update_fields=("is_deleted",))
        other = Delivery.objects.create(user=self.user, filename="delivery.zip", size_bytes=4)
        self.assertEqual(self.client.get(self.url, self.parameters).status_code, 409)
        self.assertEqual(self.post_chunk().status_code, 409)
        self.assertEqual(Delivery.objects.get(is_deleted=False).pk, other.pk)
        self.assertFalse((self.paths.chunks_dir / ".registered").exists())

    def test_nonregular_registration_receipt_returns_an_error_without_blocking(self):
        receipt = self.paths.chunks_dir / ".registered"
        receipt.symlink_to(self.paths.chunks_dir / "outside")
        self.assertEqual(self.client.get(self.url, self.parameters).status_code, 500)
        receipt.unlink()
        os.mkfifo(receipt)
        self.assertEqual(self.client.get(self.url, self.parameters).status_code, 500)

    def test_registration_rechecks_a_record_created_after_the_initial_lookup(self):
        other = Delivery.objects.create(user=self.user, filename="delivery.zip", size_bytes=4)
        with patch(
            "qc_tool.frontend.dashboard.services.uploads.registration._active_delivery",
            side_effect=[None, other],
        ):
            response = self.post_chunk()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "delivery_exists")
        self.assertFalse((self.paths.chunks_dir / ".registered").exists())
        self.assertFalse((self.paths.chunks_dir / ".registration").exists())

    def test_last_chunk_can_arrive_before_the_first_chunk(self):
        final = _parameters(chunk_number=2, chunk_size=5, current_chunk_size=7, total_chunks=2, total_size=12)
        first = {**final, "resumableChunkNumber": "1", "resumableCurrentChunkSize": "5"}
        response = self.client.post(self.url, {**final, "file": SimpleUploadedFile("chunk", b"fghijkl")})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["delivery_id"])
        self.assertEqual(self.client.get(self.url, final).status_code, 404)
        response = self.client.post(self.url, {**first, "file": SimpleUploadedFile("chunk", b"abcde")})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["delivery_id"], Delivery.objects.get().pk)
        self.assertEqual(self.paths.target_path.read_bytes(), b"abcdefghijkl")
        self.assertEqual(self.client.get(self.url, final).status_code, 200)

    def test_successful_registration_is_confirmed_without_duplicate_posts(self):
        first = self.post_chunk()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.client.get(self.url, self.parameters).status_code, 200)
        repeated = self.post_chunk()
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(first.json()["delivery_id"], repeated.json()["delivery_id"])
        self.assertEqual(Delivery.objects.count(), 1)

    def test_unrelated_existing_file_is_never_registered_or_overwritten(self):
        self.paths.target_path.write_bytes(b"keep existing")
        response = self.post_chunk()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "delivery_file_exists")
        self.assertEqual(self.paths.target_path.read_bytes(), b"keep existing")
        self.assertFalse(Delivery.objects.exists())


class ResumableRegistrationConcurrencyTests(UploadRegistrationFixture, TransactionTestCase):
    def test_concurrent_final_chunks_register_once(self):
        barrier = Barrier(2)

        def finalize(_index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return receive_registered_chunk(
                    self.descriptor, self.paths, user=self.user,
                    uploaded_chunk=SimpleUploadedFile("chunk", b"abcd"),
                ).pk
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            registered = list(executor.map(finalize, range(2)))

        self.assertEqual(registered[0], registered[1])
        self.assertEqual(Delivery.objects.count(), 1)
        self.assertEqual(self.paths.target_path.read_bytes(), b"abcd")
