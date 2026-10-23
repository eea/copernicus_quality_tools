"""Storage usage is metadata-bound and never guesses a historical input."""

from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.http import HttpResponse
from django.test import TestCase, override_settings
from django.urls import path, reverse
from django.utils import timezone

from qc_tool.frontend.dashboard.models import (
    Delivery, DeliverySubmission, Job, Product, ProductRelease, ProductUnit,
)
from qc_tool.frontend.dashboard.services.storage_admin.references import (
    MAX_REFERENCE_LINKS, StorageReferenceError, assert_restore_safe, assert_unreferenced,
    describe_references, record_storage_links,
)


def empty_view(request, **kwargs):
    return HttpResponse()


urlpatterns = [
    path("admin/database/records/<str:table>/<str:pk>/", empty_view, name="admin_database_record"),
    path("admin/storage/", empty_view, name="admin_storage"),
    path("admin/storage/file/", empty_view, name="admin_storage_file"),
]


@override_settings(ROOT_URLCONF=__name__)
class StorageReferenceTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="storage-owner")
        self.delivery = Delivery.objects.create(
            user=self.owner, filename="original.zip", size_bytes=123, content_sha256="a" * 64,
        )
        self.job = Job.objects.create(
            delivery=self.delivery, product_ident="test", product_description="Historical QC",
            input_sha256="a" * 64,
        )
        self.path = self.owner.username + "/" + self.delivery.filename

    def assert_protected(self, area, path, **kwargs):
        result = describe_references(area, path, **kwargs)
        self.assertTrue(result["protected"])
        self.assertFalse(result["can_quarantine"])
        with self.assertRaises(StorageReferenceError):
            assert_unreferenced(area, path, is_directory=kwargs.get("is_directory", False))
        return result

    def test_exact_incoming_owner_and_filename_are_linked_without_reading_files(self):
        result = self.assert_protected("incoming", self.path)
        self.assertEqual(result["status"], "linked")
        self.assertEqual(result["status_label"], "Linked")
        self.assertEqual(result["links"], result["references"])
        self.assertEqual(result["reference_count"], 2)
        self.assertEqual({item["kind"] for item in result["references"]}, {"delivery", "job"})
        self.assertEqual(result["historical_status"], "unverified")
        for item in result["references"]:
            self.assertTrue(item["url"].startswith("/admin/database/records/"))

    def test_soft_deleted_delivery_and_its_history_still_protect_the_file(self):
        self.delivery.is_deleted = True
        self.delivery.save(update_fields=["is_deleted"])
        self.assertEqual(self.assert_protected("incoming", self.path)["status"], "linked")

    def test_matching_bytes_under_another_owner_or_name_never_guess_an_association(self):
        for path in ("another-owner/original.zip", "storage-owner/another.zip"):
            with self.subTest(path=path):
                result = describe_references("incoming", path, evidence={"sha256": "a" * 64, "size": 123})
                self.assertEqual(result["status"], "unlinked")
                self.assertEqual(result["references"], [])
                self.assertEqual(result["verified_jobs"], [])
                self.assertTrue(result["can_quarantine"])

    def test_job_input_requires_both_exact_checksum_and_recorded_size(self):
        result = describe_references("incoming", self.path, evidence={"sha256": "a" * 64, "size": 123})
        self.assertEqual(result["historical_status"], "verified")
        self.assertEqual(result["verified_jobs"][0]["id"], str(self.job.pk))
        self.assertTrue(result["job_matches"][0]["verified"])
        self.assertIn("SHA-256 and recorded size", result["historical_message"])
        for evidence in ({"sha256": "b" * 64, "size": 123}, {"sha256": "a" * 64, "size": 124}):
            with self.subTest(evidence=evidence):
                failed = describe_references("incoming", self.path, evidence=evidence)
                self.assertEqual(failed["historical_status"], "unavailable")
                self.assertEqual(failed["verified_jobs"], [])
                self.assertFalse(failed["job_matches"][0]["verified"])
                self.assertTrue(failed["protected"])

    def test_job_without_input_checksum_is_honestly_historically_unavailable(self):
        self.job.input_sha256 = ""
        self.job.save(update_fields=["input_sha256"])
        result = describe_references("incoming", self.path, evidence={"sha256": "a" * 64, "size": 123})
        self.assertEqual(result["historical_status"], "unavailable")
        self.assertIn("no recorded input checksum", result["historical_message"])
        self.assertEqual(result["verified_jobs"], [])

    def test_job_directory_and_canonical_stdout_are_bound_to_the_exact_uuid(self):
        for path in ("job_" + self.job.pk.hex + "/output.d/report.pdf", f"job.{self.job.pk}.stdout"):
            with self.subTest(path=path):
                result = self.assert_protected("jobs", path)
                self.assertEqual(result["status"], "linked")
                self.assertIn(str(self.job.pk), [item["id"] for item in result["references"]])
        orphan = describe_references("jobs", "job_" + uuid4().hex + "/output.d/report.pdf")
        self.assertEqual(orphan["status"], "unlinked")
        self.assertTrue(orphan["can_quarantine"])

    def test_working_zip_input_proof_is_limited_to_the_explicit_one_level_input_location(self):
        prefix = "job_" + self.job.pk.hex + "/"
        evidence = {"sha256": "a" * 64, "size": 123}
        verified = describe_references("jobs", prefix + "input.d/original.zip", evidence=evidence)
        self.assertEqual(verified["historical_status"], "verified")
        for suffix in ("output.d/result.zip", "tmp.d/temporary.zip", "input.d/nested/original.zip", "original.zip"):
            with self.subTest(path=suffix):
                result = describe_references("jobs", prefix + suffix, evidence=evidence)
                self.assertEqual(result["status"], "linked")
                self.assertFalse(result["can_quarantine"])
                self.assertEqual(result["historical_status"], "")
                self.assertEqual(result["job_matches"], [])
                self.assertEqual(result["verified_jobs"], [])

    def test_directories_include_descendant_delivery_references_and_are_never_movable(self):
        self.assert_protected("incoming", self.owner.username, is_directory=True)
        result = describe_references("incoming", "empty-owner", is_directory=True)
        self.assertEqual(result["status"], "unlinked")
        self.assertFalse(result["can_quarantine"])

    def test_immutable_and_private_namespaces_remain_protected_without_database_rows(self):
        for area, path in (("published", "unlinked-publication/report.pdf"),
                           ("boundaries", "vector/boundary.gpkg"),
                           ("specifications", "test.json"), ("product-0", "test.json"),
                           ("jobs", "product_definitions/test.json"),
                           ("incoming", ".qc-tool-trash/operation/payload")):
            with self.subTest(area=area, path=path):
                self.assert_protected(area, path)

    def test_database_failure_cannot_turn_usage_into_unlinked_or_disclose_details(self):
        with patch.object(Delivery.objects, "filter", side_effect=DatabaseError("private database password")):
            result = self.assert_protected("incoming", self.path)
        self.assertFalse(result["checked"])
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("private database password", result["message"])

    def test_bad_paths_or_untrusted_checksum_shapes_cannot_authorize_a_move(self):
        for path in ("../owner/original.zip", "/owner/original.zip", "owner//original.zip", "owner/../original.zip"):
            with self.subTest(path=path):
                self.assert_protected("incoming", path)
        result = describe_references("incoming", self.path, evidence={"sha256": "a" * 64, "size": True})
        self.assertFalse(result["checked"])
        self.assertFalse(result["can_quarantine"])

    def test_reference_links_are_bounded_without_losing_the_protection_or_count(self):
        Job.objects.bulk_create([
            Job(delivery=self.delivery, product_ident="test", product_description="Retained QC")
            for _index in range(MAX_REFERENCE_LINKS)
        ])
        result = self.assert_protected("incoming", self.path)
        self.assertEqual(len(result["references"]), MAX_REFERENCE_LINKS)
        self.assertEqual(result["reference_count"], MAX_REFERENCE_LINKS + 2)
        self.assertTrue(result["truncated"])

    def create_submission(self):
        product = Product.objects.create(ident="test", name="Test product")
        release = ProductRelease.objects.create(
            product=product, release_key="test-release", revision=1,
            description="Test release", catalog_digest="b" * 64,
        )
        unit = ProductUnit.objects.create(product_release=release, product_unit_code="CZ", provenance="test")
        return DeliverySubmission.objects.create(
            delivery=self.delivery, job=self.job, product_release=release, product_unit=unit,
            product_unit_code="CZ", verified_product_unit_code="CZ", submitted_by=self.owner,
            submitted_by_username=self.owner.username, request_channel="browser",
            publication_state="published", published_at=timezone.now(),
            artifact_key="published/original", artifact_digest="c" * 64, input_digest="a" * 64,
        )

    def test_publication_prefix_protects_descendants_and_links_the_receipt(self):
        submission = self.create_submission()
        result = self.assert_protected("published", submission.artifact_key + "/output.d/report.pdf")
        self.assertEqual(result["status"], "linked")
        self.assertIn(str(submission.pk), [item["id"] for item in result["references"]])
        parent = self.assert_protected("published", "published", is_directory=True)
        self.assertEqual(parent["status"], "linked")

    def test_published_input_verification_uses_its_receipt_path_without_current_filename_guessing(self):
        submission = self.create_submission()
        path = submission.artifact_key + "/input.d/original-retained-name.zip"
        result = describe_references("published", path, evidence={"sha256": "a" * 64, "size": 123})
        self.assertEqual(result["historical_status"], "verified")
        self.assertEqual(result["verified_jobs"][0]["id"], str(self.job.pk))
        unrelated = describe_references("published", "another/input.d/original-retained-name.zip",
                                        evidence={"sha256": "a" * 64, "size": 123})
        self.assertEqual(unrelated["verified_jobs"], [])
        self.assertFalse(unrelated["can_quarantine"])

    def test_record_storage_links_use_exact_admin_locations_even_if_files_are_absent(self):
        resource = SimpleNamespace(model=Job)
        with self.assertNumQueries(0):
            links = record_storage_links(resource, self.job)
        self.assertEqual([item["area"] for item in links], ["jobs", "incoming"])
        self.assertEqual(links[0]["path"], "job_" + self.job.pk.hex)
        self.assertEqual(links[1]["path"], self.path)
        for link in links:
            self.assertTrue(urlsplit(link["url"]).path.startswith("/admin/storage/"))
            self.assertEqual(parse_qs(urlsplit(link["url"]).query), {"area": [link["area"]], "path": [link["path"]]})

    def test_restore_allows_unlinked_files_and_the_exact_active_delivery_zip(self):
        evidence = {"sha256": "a" * 64, "size": 123}
        self.assertTrue(assert_restore_safe("incoming", "future-owner/future.zip", evidence=evidence)["can_restore"])
        result = assert_restore_safe("incoming", self.path, evidence=evidence)
        self.assertTrue(result["can_restore"])
        self.assertFalse(result["can_quarantine"])

    def test_restore_rejects_unknown_or_conflicting_active_delivery_even_if_a_job_matches(self):
        evidence = {"sha256": "a" * 64, "size": 123}
        for checksum, size in (("", 123), ("b" * 64, 123), ("a" * 64, 124)):
            with self.subTest(checksum=checksum, size=size):
                conflicting = Delivery.objects.create(user=self.owner, filename=self.delivery.filename,
                                                       content_sha256=checksum, size_bytes=size)
                with self.assertRaises(StorageReferenceError):
                    assert_restore_safe("incoming", self.path, evidence=evidence)
                conflicting.delete()

    def test_restore_without_active_delivery_requires_a_verified_historical_job(self):
        self.delivery.is_deleted = True
        self.delivery.save(update_fields=["is_deleted"])
        evidence = {"sha256": "a" * 64, "size": 123}
        self.assertTrue(assert_restore_safe("incoming", self.path, evidence=evidence)["can_restore"])
        self.job.input_sha256 = ""
        self.job.save(update_fields=["input_sha256"])
        with self.assertRaises(StorageReferenceError):
            assert_restore_safe("incoming", self.path, evidence=evidence)

    def test_restore_does_not_allow_linked_job_artifacts_or_immutable_publications(self):
        for area, path in (("jobs", "job_" + self.job.pk.hex + "/output.d/report.pdf"),
                           ("published", "published/orphan/report.pdf")):
            with self.subTest(area=area):
                with self.assertRaises(StorageReferenceError):
                    assert_restore_safe(area, path, evidence={"sha256": "a" * 64, "size": 123})

    def test_restore_database_errors_and_missing_checksum_evidence_fail_closed(self):
        with patch.object(Delivery.objects, "filter", side_effect=DatabaseError("private detail")):
            with self.assertRaises(StorageReferenceError):
                assert_restore_safe("incoming", self.path, evidence={"sha256": "a" * 64, "size": 123})
        with self.assertRaises(StorageReferenceError):
            assert_restore_safe("incoming", self.path, evidence=None)

    def test_record_storage_links_do_not_guess_remote_ownerless_or_invalid_paths(self):
        self.delivery.user = None
        self.assertEqual(record_storage_links(SimpleNamespace(model=Delivery), self.delivery), [])
        self.delivery.user = self.owner
        self.delivery.filename = "../elsewhere.zip"
        self.assertEqual(record_storage_links(SimpleNamespace(model=Delivery), self.delivery), [])
        self.assertEqual(record_storage_links(SimpleNamespace(model=Job), self.delivery), [])

    def test_published_record_storage_link_preserves_the_recorded_artifact_key(self):
        submission = self.create_submission()
        links = record_storage_links(SimpleNamespace(model=DeliverySubmission), submission)
        self.assertEqual(len(links), 1)
        self.assertEqual((links[0]["area"], links[0]["path"]), ("published", submission.artifact_key))
