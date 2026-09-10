"""Durable submission, publication, and duplicate-AOI decision tests."""

import hashlib
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import tempfile
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.db import connection
from django.db import IntegrityError
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.test import TransactionTestCase
from django.utils import timezone

from qc_tool.common import JOB_FAILED
from qc_tool.common import JOB_OK
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import DeliverySubmission
from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.accounts.models import PersonalAccessToken
from qc_tool.frontend.dashboard.models import Product
from qc_tool.frontend.dashboard.models import ProductAOI
from qc_tool.frontend.dashboard.models import ProductRelease
from qc_tool.frontend.dashboard.models import ProductReleaseDefinition
from qc_tool.frontend.dashboard.models import QcDefinition
from qc_tool.frontend.dashboard.models import S3Info
from qc_tool.frontend.dashboard.models import SubmissionConflict
from qc_tool.frontend.dashboard.models import SubmissionConflictEvent
from qc_tool.frontend.dashboard.models import SubmissionReviewEvent
from qc_tool.frontend.dashboard.services.catalog import get_product_coverage
from qc_tool.frontend.dashboard.services.catalog import get_remaining_aoi_codes
from qc_tool.frontend.dashboard.services.submissions import PublicationError
from qc_tool.frontend.dashboard.services.submissions import SubmissionError
from qc_tool.frontend.dashboard.services.submissions import (
    resolve_submission_conflict,
)
from qc_tool.frontend.dashboard.services.submissions import submit_delivery
from qc_tool.frontend.dashboard.services.submissions import review_submission


class SubmissionFixtureMixin:
    initial_coverage_state = ProductRelease.CoverageState.AUTHORITATIVE

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.media_root = root / "incoming"
        self.submission_root = root / "published"
        self.jobs_root = root / "jobs"
        self.media_root.mkdir()
        self.jobs_root.mkdir()

        self.definition = QcDefinition.objects.create(
            product_ident="test-definition",
            digest="d" * 64,
            description="Test definition",
            document={"description": "Test definition", "steps": []},
            source_path="test-definition.json",
        )
        self.product = Product.objects.create(
            ident="test-definition",
            name="Test product",
        )
        self.release = ProductRelease.objects.create(
            product=self.product,
            release_key="test-release-2026",
            revision=1,
            description="Test release",
            catalog_digest="c" * 64,
            coverage_state=self.initial_coverage_state,
            is_current=True,
            approved_at=timezone.now(),
        )
        ProductReleaseDefinition.objects.create(
            product_release=self.release,
            qc_definition=self.definition,
            is_primary=True,
        )
        self.product_aoi = ProductAOI.objects.create(
            product_release=self.release,
            aoi_code="ee001l",
            source_value="EE001L1",
            provenance="manifest",
        )

    def create_candidate(self, username, *, status=JOB_OK, aoi="ee001l"):
        user = get_user_model().objects.create_user(
            username=username,
            password="password",
        )
        user_root = self.media_root / username
        user_root.mkdir()
        zip_payload = ("delivery for {}".format(username)).encode("utf-8")
        zip_path = user_root / "delivery.zip"
        zip_path.write_bytes(zip_payload)
        digest = hashlib.sha256(zip_payload).hexdigest()
        delivery = Delivery.objects.create(
            user=user,
            filename=zip_path.name,
            size_bytes=len(zip_payload),
            aoi_code_submitted=aoi,
        )
        job = Job.objects.create(
            delivery=delivery,
            job_status=status,
            product_ident=self.definition.product_ident,
            product_description=self.definition.description,
            aoi_code=aoi,
            aoi_code_submitted=aoi,
            input_sha256=digest,
            product_release=self.release,
            qc_definition=self.definition,
            requested_by=user,
            requested_by_username=username,
            request_source="browser",
        )
        job_root = self.jobs_root / str(job.job_uuid)
        output = job_root / "output.d"
        output.mkdir(parents=True)
        (job_root / "result.json").write_text(
            json.dumps({"status": "ok", "aoi_code": aoi}),
            encoding="utf-8",
        )
        (output / "report.txt").write_text("validated", encoding="utf-8")
        return user, delivery, job, job_root

    def owner_access(self, user):
        return SimpleNamespace(
            can_manage_user=lambda owner_id: owner_id == user.pk,
            is_administrator=False,
            is_product_manager=False,
            product_idents=frozenset(),
        )

    def submit(self, user, delivery, job_root):
        with patch(
            "qc_tool.frontend.dashboard.services.submissions.publication."
            "compose_job_dir",
            return_value=job_root,
        ):
            return submit_delivery(
                delivery_id=delivery.pk,
                actor=user,
                account_access=self.owner_access(user),
                request_channel=DeliverySubmission.RequestChannel.BROWSER,
                submission_root=self.submission_root,
                media_root=self.media_root,
            )

    def manager_access(self, *product_idents):
        allowed = frozenset(product_idents or (self.product.ident,))
        return SimpleNamespace(
            can_review_product_submission=lambda ident: ident in allowed,
        )

    def review(self, submission, actor, *, decision="approved", notes=""):
        return review_submission(
            submission_id=submission.pk, decision=decision, actor=actor,
            account_access=self.manager_access(),
            expected_review_version=submission.review_version, notes=notes,
        )


class SubmissionLifecycleTests(SubmissionFixtureMixin, TestCase):
    def test_successful_submission_is_atomic_and_idempotent(self):
        user, delivery, job, job_root = self.create_candidate("first-owner")

        first = self.submit(user, delivery, job_root)
        second = self.submit(user, delivery, job_root)

        self.assertFalse(first.idempotent)
        self.assertTrue(second.idempotent)
        self.assertEqual(first.submission_uuid, second.submission_uuid)
        self.assertEqual(DeliverySubmission.objects.count(), 1)
        submission = DeliverySubmission.objects.get()
        delivery.refresh_from_db()
        self.assertEqual(
            submission.publication_state,
            DeliverySubmission.PublicationState.PUBLISHED,
        )
        self.assertEqual(delivery.date_submitted, submission.published_at)
        self.assertEqual(delivery.content_sha256, job.input_sha256)
        self.assertEqual(submission.review_state, DeliverySubmission.ReviewState.PENDING)
        self.assertEqual(submission.review_version, 0)
        self.assertEqual(get_product_coverage(self.release).submitted, 0)
        final_directory = Path(submission.artifact_path)
        self.assertTrue(final_directory.is_dir())
        self.assertTrue((final_directory / "submission-manifest.json").is_file())
        self.assertTrue((final_directory / "output.d" / "report.txt").is_file())
        self.assertTrue((final_directory / "input.d" / "delivery.zip").is_file())

    def test_published_database_state_requires_both_integrity_digests(self):
        user, delivery, job, _job_root = self.create_candidate(
            "incomplete-published-owner"
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            DeliverySubmission.objects.create(
                delivery=delivery,
                job=job,
                product_release=self.release,
                product_aoi=self.product_aoi,
                aoi_code=self.product_aoi.aoi_code,
                aoi_code_submitted=self.product_aoi.aoi_code,
                submitted_by=user,
                submitted_by_username=user.username,
                request_channel=DeliverySubmission.RequestChannel.BROWSER,
                publication_state=(
                    DeliverySubmission.PublicationState.PUBLISHED
                ),
                published_at=timezone.now(),
                artifact_path="/published/incomplete",
                artifact_digest="a" * 64,
                input_digest="",
            )

    def test_final_receipt_rejects_save_and_bulk_rewrites(self):
        user, delivery, _job, job_root = self.create_candidate("retained-owner")
        self.submit(user, delivery, job_root)
        submission = DeliverySubmission.objects.get()
        original_digest = submission.artifact_digest
        for field, value in (
            ("artifact_digest", "f" * 64),
            ("artifact_path", "/replacement"),
            ("publication_state", "failed"),
            ("published_at", None),
            ("input_digest", "e" * 64),
        ):
            with self.subTest(field=field):
                submission.refresh_from_db()
                setattr(submission, field, value)
                with self.assertRaises(ValidationError):
                    submission.save(update_fields=(field,))
                with self.assertRaises(ValidationError):
                    DeliverySubmission.objects.filter(pk=submission.pk).update(
                        **{field: value},
                    )
        with self.assertRaises(ValidationError), transaction.atomic():
            DeliverySubmission.objects.bulk_update([submission], ["input_digest"])
        with self.assertRaises(ValidationError):
            DeliverySubmission.objects.bulk_create(
                [submission], update_conflicts=True,
                update_fields=["input_digest"], unique_fields=["submission_uuid"],
            )
        submission.refresh_from_db()
        self.assertEqual(submission.artifact_digest, original_digest)
        self.assertEqual(submission.publication_state, "published")

    def test_final_submission_and_its_dependencies_cannot_be_deleted(self):
        user, delivery, job, job_root = self.create_candidate("protected-owner")
        self.submit(user, delivery, job_root)
        submission = DeliverySubmission.objects.get()
        for record in (user, delivery, job, self.product_aoi, self.release):
            with self.subTest(model=type(record).__name__):
                with self.assertRaises(ProtectedError):
                    type(record).objects.filter(pk=record.pk).delete()
        with self.assertRaises(ValidationError):
            submission.delete()
        with self.assertRaises(ValidationError):
            DeliverySubmission.objects.all().delete()
        self.assertTrue(Path(submission.artifact_path).is_dir())
        self.assertTrue(Job.objects.filter(pk=job.pk).exists())

    def test_final_copies_survive_removal_of_upload_and_worker_artifacts(self):
        user, delivery, _job, job_root = self.create_candidate("archived-owner")
        self.submit(user, delivery, job_root)
        submission = DeliverySubmission.objects.get()
        final_directory = Path(submission.artifact_path)
        archive = final_directory / "input.d" / "delivery.zip"
        original_bytes = archive.read_bytes()
        (self.media_root / user.username / delivery.filename).unlink()
        shutil.rmtree(job_root)

        result = self.submit(user, delivery, job_root)

        self.assertTrue(result.idempotent)
        self.assertEqual(archive.read_bytes(), original_bytes)
        self.assertEqual(
            (final_directory / "output.d" / "report.txt").read_text(), "validated",
        )

    def test_final_retry_rejects_changed_files_without_replacing_them(self):
        user, delivery, _job, job_root = self.create_candidate("corrupted-owner")
        self.submit(user, delivery, job_root)
        submission = DeliverySubmission.objects.get()
        report = Path(submission.artifact_path) / "output.d" / "report.txt"
        report.write_text("changed outside the application")

        with self.assertRaises(SubmissionError) as raised:
            self.submit(user, delivery, job_root)

        self.assertEqual(raised.exception.code, "publication_manifest_mismatch")
        self.assertEqual(report.read_text(), "changed outside the application")
        submission.refresh_from_db()
        self.assertEqual(submission.publication_state, "published")

    def test_storage_sync_failure_does_not_finalize_and_can_recover(self):
        user, delivery, _job, job_root = self.create_candidate("sync-owner")
        with patch(
            "qc_tool.frontend.dashboard.services.submissions.publication."
            "sync_directory", side_effect=OSError("storage sync failed"),
        ):
            with self.assertRaises(SubmissionError):
                self.submit(user, delivery, job_root)
        delivery.refresh_from_db()
        self.assertIsNone(delivery.date_submitted)
        self.assertEqual(DeliverySubmission.objects.get().publication_state, "failed")
        self.assertEqual(len(list(self.submission_root.rglob("submission-*.d"))), 1)

        result = self.submit(user, delivery, job_root)

        self.assertTrue(result.idempotent)
        self.assertEqual(result.publication_state, "published")

    def test_s3_checksum_alone_cannot_be_published_as_retained_input(self):
        user, delivery, _job, job_root = self.create_candidate("s3-owner")
        delivery.s3 = S3Info.objects.create(
            host="https://s3.example.test", access_key="test", secret_key="test",
            bucketname="test", key_prefix="delivery",
        )
        delivery.save(update_fields=("s3",))

        with self.assertRaises(SubmissionError) as raised:
            self.submit(user, delivery, job_root)

        self.assertEqual(raised.exception.code, "s3_input_not_archived")
        delivery.refresh_from_db()
        self.assertIsNone(delivery.date_submitted)
        self.assertFalse(list(self.submission_root.rglob("submission-*.d")))

    def test_token_deletion_does_not_rewrite_submission_provenance(self):
        user, delivery, _job, job_root = self.create_candidate("token-owner")
        token = PersonalAccessToken.objects.create(
            user=user,
            name="Submission token",
            secret_digest="sha256$" + ("a" * 64),
        )
        token_id = token.pk

        with patch(
            "qc_tool.frontend.dashboard.services.submissions.publication."
            "compose_job_dir",
            return_value=job_root,
        ):
            submit_delivery(
                delivery_id=delivery.pk,
                actor=user,
                account_access=self.owner_access(user),
                request_channel=DeliverySubmission.RequestChannel.API,
                api_token=token,
                submission_root=self.submission_root,
                media_root=self.media_root,
            )
        token.delete()

        submission = DeliverySubmission.objects.get(delivery=delivery)
        self.assertEqual(submission.api_token_id, token_id)
        self.assertEqual(submission.api_token_name, "Submission token")

    def test_publication_failure_never_marks_delivery_submitted(self):
        user, delivery, _job, _job_root = self.create_candidate("failed-owner")

        with patch(
            "qc_tool.frontend.dashboard.services.submissions.lifecycle."
            "publish_reserved_submission",
            side_effect=PublicationError(
                "copy_failed",
                "Copy failed.",
                500,
            ),
        ):
            with self.assertRaisesMessage(SubmissionError, "Copy failed"):
                submit_delivery(
                    delivery_id=delivery.pk,
                    actor=user,
                    account_access=self.owner_access(user),
                    request_channel=(
                        DeliverySubmission.RequestChannel.BROWSER
                    ),
                    submission_root=self.submission_root,
                    media_root=self.media_root,
                )

        delivery.refresh_from_db()
        submission = DeliverySubmission.objects.get(delivery=delivery)
        self.assertIsNone(delivery.date_submitted)
        self.assertEqual(
            submission.publication_state,
            DeliverySubmission.PublicationState.FAILED,
        )
        self.assertEqual(submission.failure_code, "copy_failed")

    def test_unusable_submission_directory_returns_a_stable_service_error(self):
        user, delivery, _job, job_root = self.create_candidate(
            "unavailable-storage-owner"
        )
        self.submission_root.mkdir()
        release_directory = self.submission_root / (
            "release-{}-test-release-2026".format(self.release.pk)
        )
        release_directory.write_text("not a directory", encoding="utf-8")

        with self.assertRaises(SubmissionError) as raised:
            self.submit(user, delivery, job_root)

        self.assertEqual(
            raised.exception.code,
            "submission_storage_unavailable",
        )
        delivery.refresh_from_db()
        self.assertIsNone(delivery.date_submitted)
        self.assertEqual(
            DeliverySubmission.objects.get(delivery=delivery).publication_state,
            DeliverySubmission.PublicationState.PENDING,
        )

    def test_retry_recovers_immediately_after_atomic_rename(self):
        user, delivery, _job, job_root = self.create_candidate("crash-owner")

        with patch(
            "qc_tool.frontend.dashboard.services.submissions.publication."
            "compose_job_dir",
            return_value=job_root,
        ), patch(
            "qc_tool.frontend.dashboard.services.submissions.lifecycle."
            "_finalize_publication",
            side_effect=RuntimeError("simulated database outage after rename"),
        ):
            with self.assertRaises(RuntimeError):
                submit_delivery(
                    delivery_id=delivery.pk,
                    actor=user,
                    account_access=self.owner_access(user),
                    request_channel=(
                        DeliverySubmission.RequestChannel.BROWSER
                    ),
                    submission_root=self.submission_root,
                    media_root=self.media_root,
                )

        submission = DeliverySubmission.objects.get(delivery=delivery)
        self.assertEqual(
            submission.publication_state,
            DeliverySubmission.PublicationState.PUBLISHING,
        )
        result = self.submit(user, delivery, job_root)
        submission.refresh_from_db()
        self.assertTrue(result.idempotent)
        self.assertEqual(
            submission.publication_state,
            DeliverySubmission.PublicationState.PUBLISHED,
        )
        self.assertEqual(
            len(list(self.submission_root.rglob("submission-*.d"))),
            1,
        )

    def test_retry_rejects_a_symlinked_existing_manifest(self):
        user, delivery, _job, job_root = self.create_candidate(
            "unsafe-recovery-owner"
        )
        with patch(
            "qc_tool.frontend.dashboard.services.submissions.publication."
            "compose_job_dir",
            return_value=job_root,
        ), patch(
            "qc_tool.frontend.dashboard.services.submissions.lifecycle."
            "_finalize_publication",
            side_effect=RuntimeError("simulated outage after rename"),
        ):
            with self.assertRaises(RuntimeError):
                submit_delivery(
                    delivery_id=delivery.pk,
                    actor=user,
                    account_access=self.owner_access(user),
                    request_channel=(
                        DeliverySubmission.RequestChannel.BROWSER
                    ),
                    submission_root=self.submission_root,
                    media_root=self.media_root,
                )

        final_directory = next(
            self.submission_root.rglob("submission-*.d")
        )
        manifest = final_directory / "submission-manifest.json"
        outside = self.media_root.parent / "outside-manifest.json"
        outside.write_bytes(manifest.read_bytes())
        manifest.unlink()
        manifest.symlink_to(outside)

        with self.assertRaises(SubmissionError) as raised:
            self.submit(user, delivery, job_root)

        self.assertEqual(
            raised.exception.code,
            "publication_manifest_mismatch",
        )
        delivery.refresh_from_db()
        self.assertIsNone(delivery.date_submitted)

    def test_retry_rejects_tampered_published_artifacts(self):
        user, delivery, _job, job_root = self.create_candidate(
            "tampered-recovery-owner"
        )
        with patch(
            "qc_tool.frontend.dashboard.services.submissions.publication."
            "compose_job_dir",
            return_value=job_root,
        ), patch(
            "qc_tool.frontend.dashboard.services.submissions.lifecycle."
            "_finalize_publication",
            side_effect=RuntimeError("simulated outage after rename"),
        ):
            with self.assertRaises(RuntimeError):
                submit_delivery(
                    delivery_id=delivery.pk,
                    actor=user,
                    account_access=self.owner_access(user),
                    request_channel=(
                        DeliverySubmission.RequestChannel.BROWSER
                    ),
                    submission_root=self.submission_root,
                    media_root=self.media_root,
                )

        final_directory = next(self.submission_root.rglob("submission-*.d"))
        (final_directory / "output.d" / "report.txt").write_text(
            "tampered",
            encoding="utf-8",
        )

        with self.assertRaises(SubmissionError) as raised:
            self.submit(user, delivery, job_root)

        self.assertEqual(
            raised.exception.code,
            "publication_manifest_mismatch",
        )
        delivery.refresh_from_db()
        self.assertIsNone(delivery.date_submitted)

    def test_latest_unsuccessful_job_is_not_eligible(self):
        user, delivery, _job, job_root = self.create_candidate("qc-owner")
        Job.objects.create(
            delivery=delivery,
            job_status=JOB_FAILED,
            product_ident=self.definition.product_ident,
            product_description=self.definition.description,
            product_release=self.release,
            qc_definition=self.definition,
        )

        with self.assertRaisesMessage(
            SubmissionError,
            "latest QC job must finish successfully",
        ):
            self.submit(user, delivery, job_root)
        self.assertFalse(DeliverySubmission.objects.exists())

    def test_successful_job_without_a_valid_input_digest_is_not_eligible(self):
        user, delivery, job, job_root = self.create_candidate(
            "digestless-owner"
        )
        job.input_sha256 = "not-a-sha256"
        job.save(update_fields=("input_sha256",))

        with self.assertRaises(SubmissionError) as raised:
            self.submit(user, delivery, job_root)

        self.assertEqual(raised.exception.code, "input_digest_unavailable")
        self.assertFalse(DeliverySubmission.objects.exists())

    def test_retry_uses_the_immutable_reserved_input_digest(self):
        user, delivery, job, job_root = self.create_candidate(
            "digest-snapshot-owner"
        )
        original_digest = job.input_sha256
        with patch(
            "qc_tool.frontend.dashboard.services.submissions.lifecycle."
            "publish_reserved_submission",
            side_effect=PublicationError("copy_failed", "Copy failed.", 500),
        ):
            with self.assertRaises(SubmissionError):
                self.submit(user, delivery, job_root)

        job.input_sha256 = "f" * 64
        job.save(update_fields=("input_sha256",))
        result = self.submit(user, delivery, job_root)

        submission = DeliverySubmission.objects.get(delivery=delivery)
        self.assertEqual(submission.input_digest, original_digest)
        self.assertEqual(result.publication_state, "published")

    def test_unexpected_aoi_is_not_added_to_the_catalog(self):
        user, delivery, _job, job_root = self.create_candidate(
            "unknown-aoi-owner",
            aoi="ee999l",
        )

        with self.assertRaises(SubmissionError) as raised:
            self.submit(user, delivery, job_root)

        self.assertEqual(raised.exception.code, "submitted_aoi_not_expected")
        self.assertFalse(
            ProductAOI.objects.filter(aoi_code="ee999l").exists()
        )

    def test_different_users_open_conflict_without_losing_candidates(self):
        first_user, first_delivery, _first_job, first_root = (
            self.create_candidate("candidate-one")
        )
        second_user, second_delivery, _second_job, second_root = (
            self.create_candidate("candidate-two")
        )

        first = self.submit(first_user, first_delivery, first_root)
        second = self.submit(second_user, second_delivery, second_root)

        self.assertIsNone(first.conflict_id)
        self.assertIsNotNone(second.conflict_id)
        self.assertEqual(DeliverySubmission.objects.count(), 2)
        conflict = SubmissionConflict.objects.get(product_aoi=self.product_aoi)
        self.assertEqual(conflict.state, SubmissionConflict.State.OPEN)
        self.assertEqual(
            set(
                DeliverySubmission.objects.values_list(
                    "review_state", flat=True
                )
            ),
            {DeliverySubmission.ReviewState.CONFLICT},
        )
        self.assertEqual(
            list(conflict.events.values_list("event_type", flat=True)),
            [SubmissionConflictEvent.EventType.OPENED],
        )
        coverage = get_product_coverage(self.release)
        self.assertEqual(coverage.expected, 1)
        self.assertEqual(coverage.submitted, 0)
        self.assertEqual(coverage.conflicts, 1)
        self.assertEqual(coverage.remaining, 1)
        self.assertEqual(
            get_remaining_aoi_codes(self.release),
            ("ee001l",),
        )

    def test_manager_resolution_selects_one_and_new_user_reopens(self):
        first_user, first_delivery, _first_job, first_root = (
            self.create_candidate("resolution-one")
        )
        second_user, second_delivery, _second_job, second_root = (
            self.create_candidate("resolution-two")
        )
        first_result = self.submit(first_user, first_delivery, first_root)
        self.submit(second_user, second_delivery, second_root)
        conflict = SubmissionConflict.objects.get()
        manager_access = self.manager_access()

        resolution = resolve_submission_conflict(
            conflict_id=conflict.pk,
            selected_submission_id=first_result.submission_uuid,
            actor=first_user,
            account_access=manager_access,
            expected_version=conflict.version,
            notes="Preferred manager candidate",
        )

        conflict.refresh_from_db()
        self.assertEqual(conflict.state, SubmissionConflict.State.RESOLVED)
        self.assertEqual(
            conflict.selected_submission_id,
            first_result.submission_uuid,
        )
        self.assertEqual(resolution.version, 2)
        self.assertEqual(get_product_coverage(self.release).submitted, 1)
        self.assertEqual(get_remaining_aoi_codes(self.release), ())

        third_user, third_delivery, _third_job, third_root = (
            self.create_candidate("resolution-three")
        )
        self.submit(third_user, third_delivery, third_root)
        conflict.refresh_from_db()
        self.assertEqual(conflict.state, SubmissionConflict.State.OPEN)
        self.assertIsNone(conflict.selected_submission_id)
        self.assertEqual(conflict.version, 3)
        self.assertEqual(
            get_remaining_aoi_codes(self.release),
            (),
        )
        self.assertEqual(get_product_coverage(self.release).submitted, 1)
        self.assertEqual(
            list(conflict.events.values_list("event_type", flat=True)),
            [
                SubmissionConflictEvent.EventType.OPENED,
                SubmissionConflictEvent.EventType.RESOLVED,
                SubmissionConflictEvent.EventType.REOPENED,
            ],
        )

    def test_approval_counts_only_after_review_and_retains_receipt(self):
        user, delivery, _job, job_root = self.create_candidate("approval-owner")
        self.submit(user, delivery, job_root)
        submission = DeliverySubmission.objects.get(delivery=delivery)
        receipt = (submission.artifact_path, submission.artifact_digest, submission.input_digest, submission.published_at)

        self.review(submission, user, notes="Verified against the delivery plan.")

        submission.refresh_from_db()
        event = submission.review_events.get()
        self.assertEqual(submission.review_state, "accepted")
        self.assertEqual(submission.review_version, 1)
        self.assertEqual((event.decision, event.version, event.actor_username), ("approved", 1, user.username))
        self.assertEqual(get_product_coverage(self.release).submitted, 1)
        self.assertEqual(get_remaining_aoi_codes(self.release), ())
        self.assertEqual((submission.artifact_path, submission.artifact_digest, submission.input_digest, submission.published_at), receipt)
        self.assertTrue(Path(submission.artifact_path).is_dir())

    def test_decline_requires_reason_and_preserves_files(self):
        user, delivery, _job, job_root = self.create_candidate("decline-owner")
        self.submit(user, delivery, job_root)
        submission = DeliverySubmission.objects.get(delivery=delivery)
        with self.assertRaises(SubmissionError) as raised:
            self.review(submission, user, decision="declined", notes="  ")
        self.assertEqual(raised.exception.code, "review_reason_required")

        self.review(submission, user, decision="declined", notes="The submitted metadata is incomplete.")

        submission.refresh_from_db()
        self.assertEqual(submission.review_state, "rejected")
        self.assertEqual(submission.review_events.get().notes, "The submitted metadata is incomplete.")
        self.assertEqual(get_product_coverage(self.release).submitted, 0)
        self.assertTrue(Path(submission.artifact_path).is_dir())

    def test_review_denies_unassigned_accounts_and_stale_versions(self):
        user, delivery, _job, job_root = self.create_candidate("review-scope-owner")
        self.submit(user, delivery, job_root)
        submission = DeliverySubmission.objects.get(delivery=delivery)
        with self.assertRaises(SubmissionError) as raised:
            review_submission(
                submission_id=submission.pk, decision="approved", actor=user,
                account_access=self.manager_access("another-product"), expected_review_version=0,
            )
        self.assertEqual(raised.exception.status_code, 403)
        self.review(submission, user)
        with self.assertRaises(SubmissionError) as raised:
            review_submission(
                submission_id=submission.pk, decision="declined", actor=user,
                account_access=self.manager_access(), expected_review_version=0,
                notes="Attempt from an outdated form.",
            )
        self.assertEqual(raised.exception.code, "submission_review_changed")
        self.assertEqual(submission.review_events.count(), 1)

    def test_review_requires_published_files_and_active_product(self):
        user, delivery, _job, job_root = self.create_candidate("review-publishing-owner")
        with patch(
            "qc_tool.frontend.dashboard.services.submissions.lifecycle.publish_reserved_submission",
            side_effect=PublicationError("copy_failed", "Copy failed.", 500),
        ), self.assertRaises(SubmissionError):
            self.submit(user, delivery, job_root)
        submission = DeliverySubmission.objects.get(delivery=delivery)
        with self.assertRaises(SubmissionError) as raised:
            self.review(submission, user)
        self.assertEqual(raised.exception.code, "submission_not_published")
        self.submit(user, delivery, job_root)
        submission.refresh_from_db()
        self.product.is_active = False
        self.product.save(update_fields=("is_active",))
        with self.assertRaises(SubmissionError) as raised:
            self.review(submission, user)
        self.assertEqual(raised.exception.code, "product_archived")
        self.review(submission, user, decision="declined", notes="Product withdrawn.")

    def test_all_declined_candidates_close_the_conflict_without_fulfilment(self):
        first_user, first_delivery, _job, first_root = self.create_candidate("decline-conflict-one")
        second_user, second_delivery, _job, second_root = self.create_candidate("decline-conflict-two")
        self.submit(first_user, first_delivery, first_root)
        self.submit(second_user, second_delivery, second_root)
        for submission in DeliverySubmission.objects.all():
            submission.refresh_from_db()
            self.review(submission, first_user, decision="declined", notes="Incomplete deliverable.")

        conflict = SubmissionConflict.objects.get()
        self.assertEqual(conflict.state, SubmissionConflict.State.DISMISSED)
        self.assertIsNone(conflict.selected_submission_id)
        self.assertEqual(get_product_coverage(self.release).conflicts, 0)
        self.assertEqual(get_product_coverage(self.release).submitted, 0)
        self.assertEqual(SubmissionReviewEvent.objects.count(), 2)

    def test_new_candidate_does_not_revoke_approval_and_replacement_is_explicit(self):
        first_user, first_delivery, _job, first_root = self.create_candidate("replace-one")
        second_user, second_delivery, _job, second_root = self.create_candidate("replace-two")
        self.submit(first_user, first_delivery, first_root)
        first = DeliverySubmission.objects.get(delivery=first_delivery)
        self.review(first, first_user)
        self.submit(second_user, second_delivery, second_root)
        second = DeliverySubmission.objects.get(delivery=second_delivery)
        first.refresh_from_db()
        self.assertEqual(first.review_state, "accepted")
        self.assertEqual(get_product_coverage(self.release).submitted, 1)
        with self.assertRaises(SubmissionError) as raised:
            self.review(second, first_user)
        self.assertEqual(raised.exception.code, "approved_candidate_exists")
        conflict = SubmissionConflict.objects.get()
        resolve_submission_conflict(
            conflict_id=conflict.pk, selected_submission_id=second.pk,
            actor=first_user, account_access=self.manager_access(),
            expected_version=conflict.version, notes="The replacement corrects the metadata.",
        )
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.review_state, second.review_state), ("rejected", "accepted"))
        self.assertEqual(list(first.review_events.values_list("decision", flat=True)), ["approved", "declined"])
        self.assertEqual(second.review_events.get().decision, "approved")
        self.assertEqual(get_product_coverage(self.release).submitted, 1)

    def test_review_audit_survives_actor_removal_and_rejects_rewrites(self):
        user, delivery, _job, job_root = self.create_candidate("review-history-owner")
        reviewer = get_user_model().objects.create_user(username="review-history-manager")
        self.submit(user, delivery, job_root)
        submission = DeliverySubmission.objects.get(delivery=delivery)
        self.review(submission, reviewer, notes="Verified.")
        event = submission.review_events.get()
        with self.assertRaises(ValidationError):
            event.delete()
        with self.assertRaises(ValidationError):
            submission.review_events.all().delete()
        with self.assertRaises(ValidationError):
            submission.review_events.update(notes="rewritten")
        event.notes = "rewritten"
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError), transaction.atomic():
            SubmissionReviewEvent.objects.bulk_update([event], ["notes"])
        reviewer.delete()
        event.refresh_from_db()
        self.assertIsNone(event.actor_id)
        self.assertEqual(event.actor_username, "review-history-manager")

    def test_open_conflict_rejects_stale_choice_after_a_new_candidate_arrives(self):
        first_user, first_delivery, _job, first_root = self.create_candidate("stale-choice-one")
        second_user, second_delivery, _job, second_root = self.create_candidate("stale-choice-two")
        third_user, third_delivery, _job, third_root = self.create_candidate("stale-choice-three")
        first = self.submit(first_user, first_delivery, first_root)
        self.submit(second_user, second_delivery, second_root)
        version = SubmissionConflict.objects.get().version
        self.submit(third_user, third_delivery, third_root)
        conflict = SubmissionConflict.objects.get()

        with self.assertRaises(SubmissionError) as raised:
            resolve_submission_conflict(
                conflict_id=conflict.pk, selected_submission_id=first.submission_uuid,
                actor=first_user, account_access=self.manager_access(),
                expected_version=version,
            )

        self.assertEqual(raised.exception.code, "submission_conflict_changed")
        self.assertEqual(conflict.version, version + 1)
        self.assertFalse(SubmissionReviewEvent.objects.exists())

    def test_review_form_is_stale_when_another_candidate_changes(self):
        first_user, first_delivery, _job, first_root = self.create_candidate("stale-review-one")
        second_user, second_delivery, _job, second_root = self.create_candidate("stale-review-two")
        third_user, third_delivery, _job, third_root = self.create_candidate("stale-review-three")
        self.submit(first_user, first_delivery, first_root)
        self.submit(second_user, second_delivery, second_root)
        first = DeliverySubmission.objects.get(delivery=first_delivery)
        second = DeliverySubmission.objects.get(delivery=second_delivery)
        self.submit(third_user, third_delivery, third_root)
        with self.assertRaises(SubmissionError) as raised:
            self.review(first, first_user)
        self.assertEqual(raised.exception.code, "submission_review_changed")
        first.refresh_from_db()
        second.refresh_from_db()
        self.review(second, first_user, decision="declined", notes="Incomplete replacement.")
        with self.assertRaises(SubmissionError) as raised:
            self.review(first, first_user)
        self.assertEqual(raised.exception.code, "submission_review_changed")

    def test_declining_last_competitor_keeps_previous_approval_and_closes_conflict(self):
        first_user, first_delivery, _job, first_root = self.create_candidate("keep-approval-one")
        second_user, second_delivery, _job, second_root = self.create_candidate("keep-approval-two")
        self.submit(first_user, first_delivery, first_root)
        first = DeliverySubmission.objects.get(delivery=first_delivery)
        self.review(first, first_user)
        self.submit(second_user, second_delivery, second_root)
        second = DeliverySubmission.objects.get(delivery=second_delivery)

        self.review(second, first_user, decision="declined", notes="Existing delivery is complete.")

        conflict = SubmissionConflict.objects.get()
        self.assertEqual(conflict.state, SubmissionConflict.State.RESOLVED)
        self.assertEqual(conflict.selected_submission_id, first.pk)
        self.assertEqual(get_product_coverage(self.release).submitted, 1)
        self.assertEqual(get_product_coverage(self.release).conflicts, 0)
        self.assertEqual(first.review_events.count(), 1)

    def test_unscoped_manager_cannot_resolve_conflict(self):
        first_user, first_delivery, _first_job, first_root = (
            self.create_candidate("scope-one")
        )
        second_user, second_delivery, _second_job, second_root = (
            self.create_candidate("scope-two")
        )
        selected = self.submit(first_user, first_delivery, first_root)
        self.submit(second_user, second_delivery, second_root)
        conflict = SubmissionConflict.objects.get()
        access = self.manager_access("another-product")

        with self.assertRaises(SubmissionError) as raised:
            resolve_submission_conflict(
                conflict_id=conflict.pk,
                selected_submission_id=selected.submission_uuid,
                actor=first_user,
                account_access=access,
                expected_version=conflict.version,
            )
        self.assertEqual(raised.exception.status_code, 403)

    def test_conflict_history_survives_actor_deletion_and_rejects_bulk_rewrites(self):
        first_user, first_delivery, _first_job, first_root = self.create_candidate("audit-one")
        second_user, second_delivery, _second_job, second_root = self.create_candidate("audit-two")
        selected = self.submit(first_user, first_delivery, first_root)
        self.submit(second_user, second_delivery, second_root)
        manager = get_user_model().objects.create_user(username="audit-manager")
        conflict = SubmissionConflict.objects.get()
        resolve_submission_conflict(
            conflict_id=conflict.pk, selected_submission_id=selected.submission_uuid,
            actor=manager, account_access=self.manager_access(),
            expected_version=conflict.version,
        )
        event = conflict.events.get(event_type="resolved")
        with self.assertRaises(ValidationError):
            event.delete()
        with self.assertRaises(ValidationError):
            conflict.events.all().delete()
        with self.assertRaises(ValidationError):
            conflict.events.filter(pk=event.pk).update(notes="rewritten")
        event.notes = "rewritten"
        with self.assertRaises(ValidationError), transaction.atomic():
            SubmissionConflictEvent.objects.bulk_update([event], ["notes"])

        manager.delete()

        event.refresh_from_db()
        self.assertIsNone(event.actor_id)
        self.assertEqual(event.actor_username, "audit-manager")
        self.assertEqual(event.selected_submission_id, selected.submission_uuid)
        self.assertEqual(DeliverySubmission.objects.filter(publication_state="published").count(), 2)


class ConcurrentSubmissionTests(TransactionTestCase):
    """Exercise row-lock invariants against the real PostgreSQL test DB."""

    reset_sequences = True

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("Submission concurrency requires PostgreSQL locks.")
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.media_root = root / "incoming"
        self.submission_root = root / "published"
        self.jobs_root = root / "jobs"
        self.media_root.mkdir()
        self.jobs_root.mkdir()
        definition = QcDefinition.objects.create(
            product_ident="concurrent-definition",
            digest="1" * 64,
            description="Concurrent definition",
            document={"description": "Concurrent definition", "steps": []},
            source_path="concurrent-definition.json",
        )
        product = Product.objects.create(
            ident="concurrent-definition",
            name="Concurrent product",
        )
        release = ProductRelease.objects.create(
            product=product,
            release_key="concurrent-release",
            revision=1,
            description="Concurrent release",
            catalog_digest="2" * 64,
            coverage_state=ProductRelease.CoverageState.AUTHORITATIVE,
            is_current=True,
            approved_at=timezone.now(),
        )
        ProductReleaseDefinition.objects.create(
            product_release=release,
            qc_definition=definition,
            is_primary=True,
        )
        self.product_aoi = ProductAOI.objects.create(
            product_release=release,
            aoi_code="ee010l",
            provenance="manifest",
        )
        self.candidates = [
            self._candidate("concurrent-one", definition, release),
            self._candidate("concurrent-two", definition, release),
        ]

    def _candidate(self, username, definition, release):
        user = get_user_model().objects.create_user(username=username)
        user_root = self.media_root / username
        user_root.mkdir()
        payload = username.encode("utf-8")
        (user_root / "delivery.zip").write_bytes(payload)
        delivery = Delivery.objects.create(
            user=user,
            filename="delivery.zip",
            size_bytes=len(payload),
            aoi_code_submitted=self.product_aoi.aoi_code,
        )
        job = Job.objects.create(
            delivery=delivery,
            job_status=JOB_OK,
            product_ident=definition.product_ident,
            product_description=definition.description,
            aoi_code=self.product_aoi.aoi_code,
            aoi_code_submitted=self.product_aoi.aoi_code,
            input_sha256=hashlib.sha256(payload).hexdigest(),
            product_release=release,
            qc_definition=definition,
        )
        job_root = self.jobs_root / str(job.job_uuid)
        (job_root / "output.d").mkdir(parents=True)
        (job_root / "result.json").write_text("{}", encoding="utf-8")
        return user, delivery, job_root

    def test_different_users_publish_same_aoi_concurrently(self):
        barrier = Barrier(2)
        job_roots = {
            str(candidate[1].job_set.get().job_uuid): candidate[2]
            for candidate in self.candidates
        }

        def publish(candidate):
            user, delivery, _job_root = candidate
            close_old_connections()
            barrier.wait(timeout=10)
            try:
                return submit_delivery(
                    delivery_id=delivery.pk,
                    actor=user,
                    account_access=SimpleNamespace(
                        can_manage_user=lambda owner_id: owner_id == user.pk,
                    ),
                    request_channel=(
                        DeliverySubmission.RequestChannel.BROWSER
                    ),
                    submission_root=self.submission_root,
                    media_root=self.media_root,
                )
            finally:
                close_old_connections()

        with patch(
            "qc_tool.frontend.dashboard.services.submissions.publication."
            "compose_job_dir",
            side_effect=lambda job_uuid: job_roots[str(job_uuid)],
        ), ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(publish, self.candidates))

        self.assertEqual(len(results), 2)
        self.assertEqual(DeliverySubmission.objects.count(), 2)
        conflict = SubmissionConflict.objects.get(product_aoi=self.product_aoi)
        self.assertEqual(conflict.state, SubmissionConflict.State.OPEN)
        self.assertEqual(conflict.events.count(), 1)

    def test_same_delivery_concurrent_requests_create_one_submission(self):
        candidate = self.candidates[0]
        user, delivery, job_root = candidate
        barrier = Barrier(2)

        def publish(_index):
            close_old_connections()
            barrier.wait(timeout=10)
            try:
                try:
                    return submit_delivery(
                        delivery_id=delivery.pk,
                        actor=user,
                        account_access=SimpleNamespace(
                            can_manage_user=lambda owner_id: owner_id == user.pk,
                        ),
                        request_channel=(
                            DeliverySubmission.RequestChannel.BROWSER
                        ),
                        submission_root=self.submission_root,
                        media_root=self.media_root,
                    )
                except SubmissionError as exc:
                    return exc.code
            finally:
                close_old_connections()

        with patch(
            "qc_tool.frontend.dashboard.services.submissions.publication."
            "compose_job_dir",
            return_value=job_root,
        ), ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(publish, range(2)))

        self.assertEqual(DeliverySubmission.objects.count(), 1)
        submission = DeliverySubmission.objects.get()
        self.assertEqual(
            submission.publication_state,
            DeliverySubmission.PublicationState.PUBLISHED,
        )
        result_ids = {
            outcome.submission_uuid
            for outcome in outcomes
            if not isinstance(outcome, str)
        }
        self.assertLessEqual(len(result_ids), 1)
        self.assertTrue(
            all(
                not isinstance(outcome, str)
                or outcome == "submission_in_progress"
                for outcome in outcomes
            )
        )
