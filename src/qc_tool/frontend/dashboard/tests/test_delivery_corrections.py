"""Corrections replace owned scratch inputs while retaining reviewed receipts."""

import hashlib
import json
from uuid import uuid4
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from qc_tool.common import JOB_OK
from qc_tool.frontend.dashboard.models import Delivery, DeliverySubmission, Job
from qc_tool.frontend.dashboard.services.catalog import get_product_coverage
from qc_tool.frontend.dashboard.services.submissions import SubmissionError
from qc_tool.frontend.dashboard.services.uploads import ResumableUploadDescriptor
from qc_tool.frontend.dashboard.services.tests.test_resumable_uploads import _parameters
from qc_tool.frontend.dashboard.tests.test_submission_workspace import SubmissionWorkspaceFixtureMixin


@override_settings(SUBMISSION_ENABLED=True, MAINTENANCE_MODE=False)
class DeliveryCorrectionTests(SubmissionWorkspaceFixtureMixin, TestCase):
    corrected_bytes = b"corrected delivery archive"

    def setUp(self):
        super().setUp()
        storage = override_settings(MEDIA_ROOT=self.media_root)
        storage.enable()
        self.addCleanup(storage.disable)
        previous_path = self.media_root / self.owner.username / self.delivery.filename
        self.delivery.filename = "CLC_CZ_2026_delivery.zip"
        previous_path.rename(previous_path.with_name(self.delivery.filename))
        self.delivery.save(update_fields=("filename",))
        self.submission = self.published()
        self.original_bytes = (self.media_root / self.owner.username / self.delivery.filename).read_bytes()
        self.receipt = (
            self.submission.artifact_key, self.submission.artifact_digest,
            self.submission.input_digest, self.submission.published_at,
        )
        self.client.force_login(self.owner)
        self.check_url = reverse("delivery_upload_check")
        self.upload_url = reverse("resumable_upload")
        self.parameters = {
            **_parameters(
                identifier="correction-upload", filename=self.delivery.filename,
                chunk_size=len(self.corrected_bytes),
                current_chunk_size=len(self.corrected_bytes), total_size=len(self.corrected_bytes),
            ),
            "overwrite_delivery_id": str(self.delivery.pk),
            "correction_submission_id": str(self.submission.pk),
        }

    def reject(self):
        self.review(self.submission, self.manager, decision="declined", notes="Correct the boundary extent.")
        self.submission.refresh_from_db()

    def check(self, *, filename=None, submission_id=None):
        return self.client.post(self.check_url, {
            "filenames": [self.delivery.filename if filename is None else filename],
            "correction_submission_id": str(self.submission.pk if submission_id is None else submission_id),
        }, content_type="application/json")

    def upload(self, *, data=None, **parameters):
        return self.client.post(self.upload_url, {
            **self.parameters, **parameters,
            "file": SimpleUploadedFile("chunk", self.corrected_bytes if data is None else data),
        })

    def assert_original_intact(self):
        self.delivery.refresh_from_db()
        self.assertFalse(self.delivery.is_deleted)
        self.assertEqual((self.media_root / self.owner.username / self.delivery.filename).read_bytes(), self.original_bytes)
        self.assertEqual(Delivery.objects.count(), 1)

    def assert_retained_receipt(self):
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.review_state, DeliverySubmission.ReviewState.REJECTED)
        self.assertEqual(self.submission.review_events.get().notes, "Correct the boundary extent.")
        self.assertEqual((
            self.submission.artifact_key, self.submission.artifact_digest,
            self.submission.input_digest, self.submission.published_at,
        ), self.receipt)
        self.assertEqual(((self.submission_root / self.submission.artifact_key) / "input.d" / self.delivery.filename).read_bytes(), self.original_bytes)
        response = self.client.get(reverse("submission_file", args=(self.submission.pk, "input.d/" + self.delivery.filename)))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), self.original_bytes)

    def test_preflight_allows_same_name_only_for_an_explicit_owned_rejected_correction(self):
        self.reject()
        response = self.check()
        self.assertEqual(response.status_code, 200, response.content)
        item = response.json()["files"][0]
        self.assertTrue(item["exists"])
        self.assertTrue(item["can_overwrite"])
        self.assertEqual(item["delivery_id"], self.delivery.pk)
        ordinary = self.client.post(self.check_url, {"filenames": [self.delivery.filename]}, content_type="application/json")
        self.assertFalse(ordinary.json()["files"][0]["can_overwrite"])
        self.assert_original_intact()

    def test_different_or_differently_cased_filename_cannot_pass_preflight(self):
        self.reject()
        for filename in ("different.zip", self.delivery.filename.upper()):
            with self.subTest(filename=filename):
                response = self.check(filename=filename)
                self.assertEqual(response.status_code, 400, response.content)
                self.assertEqual(response.json()["code"], "correction_filename_mismatch")
        self.assert_original_intact()

    def test_direct_chunk_upload_and_probe_cannot_bypass_filename_rule(self):
        self.reject()
        parameters = {**self.parameters, "resumableFilename": "different.zip"}
        for response in (
            self.client.get(self.upload_url, parameters),
            self.upload(resumableFilename="different.zip"),
        ):
            self.assertEqual(response.status_code, 400, response.content)
            self.assertEqual(response.json()["code"], "correction_filename_mismatch")
        self.assert_original_intact()

    def test_missing_or_foreign_correction_ids_do_not_disclose_or_replace_submissions(self):
        self.reject()
        submission_id = uuid4()
        for response in (self.check(submission_id=submission_id), self.upload(correction_submission_id=str(submission_id))):
            self.assertEqual(response.status_code, 404, response.content)
            self.assertEqual(response.json()["code"], "correction_not_available")
        for user in (self.manager, self.unassigned, self.admin):
            self.client.force_login(user)
            with self.subTest(user=user.username):
                for response in (self.check(), self.upload(), self.client.get(self.upload_url, self.parameters)):
                    self.assertEqual(response.status_code, 404, response.content)
                    self.assertEqual(response.json()["code"], "correction_not_available")
        self.assert_original_intact()

    def test_invalid_correction_reference_is_rejected_before_storage(self):
        self.reject()
        for response in (self.check(submission_id="invalid-uuid"), self.upload(correction_submission_id="invalid-uuid")):
            self.assertEqual(response.status_code, 400, response.content)
            self.assertEqual(response.json()["code"], "invalid_correction_submission")
        self.assert_original_intact()

    def test_pending_and_approved_submissions_cannot_be_replaced_as_corrections(self):
        for state in (DeliverySubmission.ReviewState.PENDING, DeliverySubmission.ReviewState.ACCEPTED):
            if state == DeliverySubmission.ReviewState.ACCEPTED:
                self.review(self.submission, self.manager)
            with self.subTest(state=state):
                for response in (self.check(), self.upload()):
                    self.assertEqual(response.status_code, 409, response.content)
                    self.assertEqual(response.json()["code"], "correction_not_available")
            self.assert_original_intact()

    def test_correction_cannot_select_another_overwrite_identity(self):
        self.reject()
        response = self.upload(overwrite_delivery_id=str(self.delivery.pk + 1000))
        self.assertGreaterEqual(response.status_code, 400, response.content)
        self.assert_original_intact()

    def test_removing_correction_reference_cannot_bypass_retained_input_protection(self):
        self.reject()
        parameters = {key: value for key, value in self.parameters.items() if key != "correction_submission_id"}
        response = self.client.post(self.upload_url, {
            **parameters, "file": SimpleUploadedFile("chunk", self.corrected_bytes),
        })
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["code"], "overwrite_not_allowed")
        self.assert_original_intact()

    def test_review_state_is_rechecked_between_chunks(self):
        self.reject()
        parameters = {
            "resumableChunkSize": "5", "resumableCurrentChunkSize": "5",
            "resumableTotalSize": "10", "resumableTotalChunks": "2",
        }
        first = self.upload(data=b"first", **parameters)
        self.assertEqual(first.status_code, 200, first.content)
        self.assert_original_intact()
        DeliverySubmission.objects.filter(pk=self.submission.pk).update(review_state=DeliverySubmission.ReviewState.ACCEPTED)
        for response in (
            self.client.get(self.upload_url, {**self.parameters, **parameters, "resumableChunkNumber": "2"}),
            self.upload(data=b"last!", resumableChunkNumber="2", **parameters),
        ):
            self.assertEqual(response.status_code, 409, response.content)
            self.assertEqual(response.json()["code"], "correction_not_available")
        self.assert_original_intact()

    def test_retained_original_must_be_verified_before_working_input_is_replaced(self):
        self.reject()
        archive = (self.submission_root / self.submission.artifact_key) / "input.d" / self.delivery.filename
        archive.write_bytes(b"tampered archive")
        response = self.upload()
        self.assertEqual(response.status_code, 503, response.content)
        self.assertEqual(response.json()["code"], "correction_archive_unavailable")
        self.assert_original_intact()
        archive.write_bytes(self.original_bytes)
        response = self.upload()
        self.assertEqual(response.status_code, 200, response.content)
        self.assert_retained_receipt()

    def test_same_name_correction_creates_fresh_delivery_and_retries_without_rewriting_receipt(self):
        self.reject()
        response = self.upload()
        self.assertEqual(response.status_code, 200, response.content)
        corrected = Delivery.objects.get(pk=response.json()["delivery_id"])
        self.assertNotEqual(corrected.pk, self.delivery.pk)
        self.assertEqual(corrected.filename, self.delivery.filename)
        self.assertEqual(corrected.user_id, self.owner.pk)
        self.assertIsNone(corrected.date_submitted)
        self.assertIsNone(corrected.verified_product_unit_code)
        self.assertFalse(Job.objects.filter(delivery=corrected).exists())
        self.delivery.refresh_from_db()
        self.assertTrue(self.delivery.is_deleted)
        self.assertEqual(Job.objects.get(pk=self.job.pk).delivery_id, self.delivery.pk)
        self.assertEqual((self.media_root / self.owner.username / corrected.filename).read_bytes(), self.corrected_bytes)
        self.assert_retained_receipt()
        self.assertEqual(self.client.get(self.upload_url, self.parameters).status_code, 200)
        self.assertEqual(self.upload().json()["delivery_id"], corrected.pk)
        self.assertEqual(Delivery.objects.count(), 2)
        self.assert_retained_receipt()
        self.assertEqual(self.upload(resumableIdentifier="another-correction").status_code, 409)
        self.assertEqual(self.check().status_code, 409)
        review = self.client.get(self.review_url(self.submission))
        self.assertIsNone(review.context["correction"])

    def test_correction_identity_is_required_and_bound_to_staged_chunks(self):
        self.reject()
        descriptor = ResumableUploadDescriptor.from_mapping(self.parameters)
        ordinary = ResumableUploadDescriptor.from_mapping({
            key: value for key, value in self.parameters.items() if key != "correction_submission_id"
        })
        self.assertNotEqual(descriptor.storage_key, ordinary.storage_key)
        parameters = {key: value for key, value in self.parameters.items() if key != "overwrite_delivery_id"}
        response = self.client.post(self.upload_url, {**parameters, "file": SimpleUploadedFile("chunk", self.corrected_bytes)})
        self.assertEqual(response.json()["code"], "correction_target_required")
        self.assert_original_intact()

    def test_review_change_during_assembly_is_rechecked_before_retirement(self):
        from qc_tool.frontend.dashboard.services.uploads.overwrite import _write_assembly
        self.reject()

        def assemble_and_change_review(*args, **kwargs):
            _write_assembly(*args, **kwargs)
            DeliverySubmission.objects.filter(pk=self.submission.pk).update(review_state="accepted")

        with patch("qc_tool.frontend.dashboard.services.uploads.overwrite._write_assembly", side_effect=assemble_and_change_review):
            response = self.upload()
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["code"], "overwrite_not_allowed")
        self.assert_original_intact()

    def test_operator_recovery_reconstructs_correction_identity_without_replacing_twice(self):
        self.reject()
        with patch("qc_tool.frontend.dashboard.services.uploads.registration._write_receipt", side_effect=OSError("interrupted receipt")):
            response = self.upload()
        self.assertEqual(response.status_code, 503, response.content)
        successor = Delivery.objects.get(is_deleted=False)
        descriptor = ResumableUploadDescriptor.from_mapping(self.parameters)
        call_command("recover_delivery_overwrite", delivery_id=self.delivery.pk,
                     upload_key=descriptor.storage_key, apply=True, stdout=StringIO())
        self.assertEqual(self.upload().json()["delivery_id"], successor.pk)
        self.assertEqual(Delivery.objects.count(), 2)
        self.assert_retained_receipt()

    def test_corrected_delivery_requires_new_qc_then_can_be_resubmitted_and_approved(self):
        self.reject()
        response = self.upload()
        self.assertEqual(response.status_code, 200, response.content)
        corrected = Delivery.objects.get(pk=response.json()["delivery_id"])
        with self.assertRaises(SubmissionError) as raised:
            self.submit(self.owner, corrected, self.job_root)
        self.assertEqual(raised.exception.code, "qc_job_required")
        self.assertEqual(DeliverySubmission.objects.count(), 1)

        job = Job.objects.create(
            delivery=corrected, job_status=JOB_OK,
            product_ident=self.definition.product_ident,
            product_description=self.definition.description,
            product_unit_code=self.product_unit.product_unit_code, verified_product_unit_code=self.product_unit.product_unit_code,
            input_sha256=hashlib.sha256(self.corrected_bytes).hexdigest(),
            product_release=self.release, qc_definition=self.definition,
            requested_by=self.owner, requested_by_username=self.owner.username,
            request_source="browser",
        )
        job_root = self.jobs_root / str(job.job_uuid)
        (job_root / "output.d").mkdir(parents=True)
        (job_root / "result.json").write_text(json.dumps({"status": "ok", "product_unit_code": self.product_unit.product_unit_code}), encoding="utf-8")
        (job_root / "output.d" / "report.txt").write_text("corrected and validated", encoding="utf-8")
        result = self.submit(self.owner, corrected, job_root)
        resubmission = DeliverySubmission.objects.get(pk=result.submission_uuid)
        self.assertNotEqual(resubmission.pk, self.submission.pk)
        self.assertEqual(resubmission.job_id, job.pk)
        self.assertEqual(resubmission.review_state, DeliverySubmission.ReviewState.PENDING)
        self.assertEqual(resubmission.input_digest, job.input_sha256)
        self.assertEqual(((self.submission_root / resubmission.artifact_key) / "input.d" / corrected.filename).read_bytes(), self.corrected_bytes)
        self.assertEqual(get_product_coverage(self.release).accepted, 0)
        self.assert_retained_receipt()

        self.review(resubmission, self.manager, notes="The corrected boundary is approved.")
        resubmission.refresh_from_db()
        self.assertEqual(resubmission.review_state, DeliverySubmission.ReviewState.ACCEPTED)
        self.assertEqual(get_product_coverage(self.release).accepted, 1)
        self.assert_retained_receipt()
