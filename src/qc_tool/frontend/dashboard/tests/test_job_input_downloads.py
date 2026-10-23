"""Historical ZIP downloads bind authorized jobs to exact retained bytes."""

import hashlib
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from qc_tool.common import CONFIG
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.dashboard.models import Delivery, DeliverySubmission, Job, Product, ProductRelease, ProductUnit
from qc_tool.frontend.dashboard.services.artifacts.inputs import job_input_availability, open_job_input


class JobInputDownloadTests(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.incoming = self.root / "incoming"
        self.submissions = self.root / "submissions"
        self.incoming.mkdir()
        self.submissions.mkdir()
        configured = override_settings(MEDIA_ROOT=str(self.incoming))
        configured.enable()
        self.addCleanup(configured.disable)
        storage = patch.dict(CONFIG, {"incoming_dir": self.incoming, "submission_dir": self.submissions})
        storage.start()
        self.addCleanup(storage.stop)
        self.owner = get_user_model().objects.create_user("zip-owner")
        UserProductGrant.objects.create(user=self.owner, product_ident="checked-product")
        self.data = b"the exact original ZIP checked by QC"
        self.digest = hashlib.sha256(self.data).hexdigest()
        self.upload = self.incoming / self.owner.username / "original.zip"
        self.upload.parent.mkdir()
        self.upload.write_bytes(self.data)
        self.delivery = Delivery.objects.create(
            user=self.owner, filename=self.upload.name, size_bytes=len(self.data),
            product_ident="checked-product", content_sha256=self.digest,
        )
        self.product = Product.objects.create(ident="checked-product", name="Checked product")
        self.release = ProductRelease.objects.create(
            product=self.product, release_key="checked-release", revision=1,
            catalog_digest="a" * 64,
        )
        self.unit = ProductUnit.objects.create(product_release=self.release, product_unit_code="CZ")
        self.job = Job.objects.create(
            delivery=self.delivery, job_status="ok", product_ident=self.product.ident,
            product_description=self.product.name, product_release=self.release,
            product_unit_code=self.unit.product_unit_code, verified_product_unit_code=self.unit.product_unit_code,
            input_sha256=self.digest,
        )
        self.client.force_login(self.owner)

    @property
    def url(self):
        return reverse("job_input_zip", args=(self.job.pk,))

    def response_bytes(self, response):
        # Django's test streaming wrapper closes the response while temporarily
        # disconnecting connection cleanup. A second close would terminate the
        # surrounding PostgreSQL TestCase transaction.
        return b"".join(response.streaming_content)

    def publish(self, *, manifest_changes=None, source_identity=None):
        submission = DeliverySubmission.objects.create(
            delivery=self.delivery, job=self.job, product_release=self.release,
            product_unit=self.unit, product_unit_code=self.unit.product_unit_code,
            verified_product_unit_code=self.unit.product_unit_code,
            submitted_by=self.owner, submitted_by_username=self.owner.username,
            request_channel="browser", input_digest=self.digest,
        )
        key = "retained/submission-" + str(submission.pk)
        directory = self.submissions / key
        (directory / "input.d").mkdir(parents=True)
        (directory / "output.d").mkdir()
        (directory / "input.d" / self.upload.name).write_bytes(self.data)
        (directory / "SUBMITTED").write_bytes(b"")
        body = {
            "schema_version": 2, "submission_id": str(submission.pk),
            "delivery_id": self.delivery.pk, "job_id": str(self.job.pk),
            "product_release_id": self.release.pk, "product_unit_id": self.unit.pk,
            "product_unit_code": self.unit.product_unit_code, "submitted_product_unit_code": self.unit.product_unit_code,
            "input_sha256": self.digest, "storage": "local",
            "requested_at": submission.requested_at.isoformat(),
            "files": [
                {"path": "input.d/" + self.upload.name, "size": len(self.data), "sha256": self.digest},
                {"path": "SUBMITTED", "size": 0, "sha256": hashlib.sha256(b"").hexdigest()},
            ],
        }
        body.update(source_identity or {})
        body.update(manifest_changes or {})
        canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(canonical).hexdigest()
        (directory / "submission-manifest.json").write_text(json.dumps({**body, "artifact_sha256": digest}))
        submission.publication_state = "published"
        submission.published_at = timezone.now()
        submission.artifact_key = key
        submission.artifact_digest = digest
        submission.save()
        self.delivery.is_deleted = True
        self.delivery.save(update_fields=("is_deleted",))
        return submission, directory

    def test_exact_canonical_input_streams_authorized_original(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertEqual(self.response_bytes(response), self.data)

    def test_same_filename_same_size_different_bytes_never_downloads(self):
        self.upload.write_bytes(b"x" * len(self.data))
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_current_delivery_download_enforces_its_recorded_checksum(self):
        url = reverse("download_delivery_file", args=(self.delivery.pk,))
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.response_bytes(response), self.data)
        self.upload.write_bytes(b"x" * len(self.data))
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_legacy_current_delivery_without_checksum_preserves_download(self):
        self.delivery.content_sha256 = None
        self.delivery.save(update_fields=("content_sha256",))
        response = self.client.get(reverse("download_delivery_file", args=(self.delivery.pk,)))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.response_bytes(response), self.data)

    def test_size_is_checked_independently_of_digest(self):
        self.delivery.size_bytes += 1
        self.delivery.save(update_fields=("size_bytes",))
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_missing_or_invalid_historical_digest_never_infers_current_file_hash(self):
        for digest in ("", "A" * 64, "not-a-checksum"):
            Job.objects.filter(pk=self.job.pk).update(input_sha256=digest)
            with self.subTest(digest=digest):
                self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.upload.read_bytes(), self.data)

    def test_deleted_delivery_has_no_current_upload_fallback(self):
        self.delivery.is_deleted = True
        self.delivery.save(update_fields=("is_deleted",))
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_published_original_survives_deleted_delivery_and_changed_current_filename(self):
        _submission, _directory = self.publish()
        self.upload.write_bytes(b"x" * len(self.data))
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.response_bytes(response), self.data)

    def test_published_input_mutation_fails_checksum(self):
        _submission, directory = self.publish()
        (directory / "input.d" / self.upload.name).write_bytes(b"x" * len(self.data))
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_self_consistent_manifest_for_another_job_is_rejected(self):
        self.publish(manifest_changes={"job_id": str(uuid4())})
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_self_consistent_manifest_for_another_submission_is_rejected(self):
        self.publish(manifest_changes={"submission_id": str(uuid4())})
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_source_integer_id_mapping_preserves_original_manifest(self):
        source = {"delivery_id": 120, "product_release_id": 130, "product_unit_id": 140}
        _submission, directory = self.publish(source_identity=source)
        original = (directory / "submission-manifest.json").read_bytes()
        with patch("qc_tool.database.transfers.provenance.publication_identity", return_value=source):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.response_bytes(response), self.data)
        self.assertEqual((directory / "submission-manifest.json").read_bytes(), original)

    def test_source_mapping_cannot_replace_stable_job_identity(self):
        other_uuid = str(uuid4())
        self.publish(manifest_changes={"job_id": other_uuid})
        with patch("qc_tool.database.transfers.provenance.publication_identity", return_value={"job_id": other_uuid}):
            self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_source_mapping_does_not_override_mismatching_local_parent_graph(self):
        self.publish()
        other = ProductRelease.objects.create(
            product=self.product, release_key="different", revision=1, catalog_digest="b" * 64,
        )
        Job.objects.filter(pk=self.job.pk).update(product_release=other)
        with patch("qc_tool.database.transfers.provenance.publication_identity") as provenance:
            self.assertEqual(self.client.get(self.url).status_code, 404)
        provenance.assert_not_called()

    def test_file_and_owner_symlinks_are_rejected(self):
        retained = self.root / "retained.zip"
        retained.write_bytes(self.data)
        self.upload.unlink()
        self.upload.symlink_to(retained)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.upload.unlink()
        self.upload.parent.rmdir()
        self.upload.parent.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_authorization_precedes_all_artifact_reads(self):
        other = get_user_model().objects.create_user("different-owner")
        UserProductGrant.objects.create(user=other, product_ident=self.product.ident)
        self.client.force_login(other)
        with patch("qc_tool.frontend.dashboard.views.jobs.artifacts.open_job_input") as opener:
            self.assertEqual(self.client.get(self.url).status_code, 403)
        opener.assert_not_called()

    def test_job_scope_does_not_follow_changed_delivery_product(self):
        UserProductGrant.objects.filter(user=self.owner).update(product_ident="different-product")
        self.delivery.product_ident = "different-product"
        self.delivery.save(update_fields=("product_ident",))
        with patch("qc_tool.frontend.dashboard.views.jobs.artifacts.open_job_input") as opener:
            self.assertEqual(self.client.get(self.url).status_code, 403)
        opener.assert_not_called()

    def test_returned_descriptor_survives_path_replacement(self):
        with open_job_input(self.job) as stream:
            self.upload.unlink()
            self.upload.write_bytes(b"new filename occupant")
            self.assertEqual(stream.read(), self.data)

    def test_availability_does_not_hash_large_upload_on_page_render(self):
        with patch("qc_tool.frontend.dashboard.services.artifacts.inputs._verified_stream") as verifier:
            availability = job_input_availability(self.job)
        verifier.assert_not_called()
        self.assertTrue(availability["available"])
        self.assertIn("when downloaded", availability["message"])

    def test_missing_checksum_has_clear_unavailable_state(self):
        self.job.input_sha256 = ""
        with patch("qc_tool.frontend.dashboard.services.artifacts.inputs._current_upload") as opener:
            state = job_input_availability(self.job)
        opener.assert_not_called()
        self.assertFalse(state["available"])
        self.assertIn("no recorded input checksum", state["message"])

    def test_result_links_to_job_bound_input_for_retained_deleted_publication(self):
        self.publish()
        with patch("qc_tool.frontend.dashboard.views.jobs.results.compile_job_report_data", return_value={"steps": []}):
            response = self.client.get(reverse("show_result", args=(self.job.pk,)))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.url)
        self.assertNotContains(response, reverse("download_delivery_file", args=(self.delivery.pk,)))
