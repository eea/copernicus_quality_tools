"""Submitted-file inventory keeps approvals, history and availability distinct."""

from pathlib import Path
import tempfile
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection
from django.http import HttpResponse
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import path
from django.utils import timezone

from qc_tool.frontend.dashboard.models import (
    Delivery, DeliverySubmission, Job, Product, ProductRelease, ProductUnit,
)
from qc_tool.frontend.dashboard.services.storage_admin import files
from qc_tool.frontend.dashboard.services.storage_admin.deliveries import inventory
from qc_tool.frontend.dashboard.services.maintenance.reads import read_only_database_access


_inspect_entry = files.inspect_entry


def empty_view(request, **kwargs):
    return HttpResponse()


urlpatterns = [
    path("admin/database/records/<str:table>/<str:pk>/", empty_view, name="admin_database_record"),
    path("admin/storage/", empty_view, name="admin_storage"),
    path("admin/storage/file/", empty_view, name="admin_storage_file"),
    path("admin/storage/download/", empty_view, name="admin_storage_download"),
    path("admin/storage/archive/", empty_view, name="admin_storage_archive"),
]


@override_settings(ROOT_URLCONF=__name__)
class StorageDeliveryInventoryTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="delivery-owner")
        self.product = Product.objects.create(ident="test-product", name="Test product")
        self.release = ProductRelease.objects.create(
            product=self.product, release_key="test-release", revision=1,
            description="Test release", catalog_digest="a" * 64, is_current=True,
        )
        self.sequence = 0
        inspector = patch.object(files, "inspect_entry", side_effect=self.safe_entry)
        self.inspect = inspector.start()
        self.addCleanup(inspector.stop)

    @staticmethod
    def safe_entry(area, path):
        return {"kind": "directory" if area == "published" else "file"}

    def receipt(self, *, publication="published", review="pending", release=None, filename=None):
        self.sequence += 1
        release = release or self.release
        delivery = Delivery.objects.create(
            user=self.owner, filename=filename or f"delivery-{self.sequence}.zip", size_bytes=123,
            product_ident=self.product.ident, product_description=self.product.name,
            date_submitted=timezone.now() if publication == "published" else None,
        )
        job = Job.objects.create(
            delivery=delivery, product_ident=self.product.ident, product_description=self.product.name,
        )
        unit = ProductUnit.objects.create(
            product_release=release, product_unit_code=f"unit-{self.sequence}", provenance="test",
        )
        return DeliverySubmission.objects.create(
            delivery=delivery, job=job, product_release=release, product_unit=unit,
            product_unit_code=unit.product_unit_code, verified_product_unit_code=unit.product_unit_code,
            submitted_by=self.owner, submitted_by_username="original-submitter",
            request_channel="browser", publication_state=publication, review_state=review,
            published_at=timezone.now() if publication == "published" else None,
            artifact_key=f"release/unit/submission-{self.sequence}" if publication == "published" else "",
            artifact_digest="b" * 64 if publication == "published" else "",
            input_digest="c" * 64 if publication == "published" else "",
        )

    def historical(self, **changes):
        defaults = dict(
            user=self.owner, filename="historical.zip", size_bytes=123,
            product_ident="historical-product", date_submitted=timezone.now(),
        )
        defaults.update(changes)
        return Delivery.objects.create(**defaults)

    def test_all_includes_receipts_and_historical_submissions_but_not_unsubmitted_uploads(self):
        receipt = self.receipt()
        legacy = self.historical()
        self.historical(filename="never-submitted.zip", date_submitted=None)
        result = inventory()
        self.assertTrue(result["available"])
        self.assertEqual(result["total"], 2)
        self.assertEqual({item["kind"] for item in result["entries"]}, {"submission", "historical"})
        self.assertEqual(result["entries"][0]["delivery_id"], legacy.pk)
        modern = next(item for item in result["entries"] if not item["is_historical"])
        self.assertEqual(modern["id"], str(receipt.pk))
        self.assertEqual(modern["submitted_by_username"], "original-submitter")
        self.assertTrue(modern["submitter_is_snapshot"])

    def test_published_is_distinct_from_approved_and_file_presence_never_implies_approval(self):
        self.receipt(review="pending")
        approved = self.receipt(review="accepted")
        self.receipt(publication="pending", review="accepted")
        self.historical()
        result = inventory(status="approved")
        self.assertEqual(result["total"], 1)
        entry = result["entries"][0]
        self.assertEqual(entry["id"], str(approved.pk))
        self.assertTrue(entry["is_approved"])
        self.assertEqual(entry["status_label"], "Approved")
        self.assertEqual(entry["approval_scope"], "Current delivery plan")
        pending = inventory(status="pending")["entries"][0]
        self.assertTrue(pending["location"]["available"])
        self.assertFalse(pending["is_approved"])
        self.assertEqual(pending["review_label"], "Awaiting review")

    def test_approval_for_previous_plan_remains_explicitly_historical(self):
        old_release = ProductRelease.objects.create(
            product=self.product, release_key="old-release", revision=1,
            description="Earlier release", catalog_digest="d" * 64,
        )
        self.receipt(review="accepted", release=old_release)
        entry = inventory(status="approved")["entries"][0]
        self.assertTrue(entry["is_approved"])
        self.assertFalse(entry["release_is_current"])
        self.assertEqual(entry["approval_scope"], "Earlier delivery plan")
        self.assertIn("earlier delivery plan", entry["status_message"])

    def test_historical_records_never_infer_approval_or_historical_byte_identity(self):
        self.historical()
        entry = inventory(status="historical")["entries"][0]
        self.assertEqual(entry["status_label"], "Historical submission")
        self.assertEqual(entry["review_label"], "Approval unknown")
        self.assertFalse(entry["is_approved"])
        self.assertFalse(entry["submitter_is_snapshot"])
        self.assertEqual(entry["location"]["label"], "Current upload available")
        self.assertIn("not been verified", entry["location"]["message"])
        parsed = urlsplit(entry["download_url"])
        self.assertEqual(parsed.path, "/admin/storage/download/")
        self.assertEqual(parse_qs(parsed.query)["path"], ["delivery-owner/historical.zip"])

    def test_receipt_inventory_is_paginated_in_database_and_probes_only_visible_rows(self):
        for _index in range(4):
            self.receipt()
        with self.assertNumQueries(3):
            first = inventory(page_size=2)
        self.assertEqual(first["total_count"], 4)
        self.assertEqual(len(first["entries"]), 2)
        self.assertEqual(self.inspect.call_count, 2)
        self.assertTrue(first["has_next"])
        self.assertFalse(first["has_previous"])
        second = inventory(page=2, page_size=2)
        self.assertTrue(second["has_previous"])
        self.assertFalse(second["has_next"])
        self.assertFalse({item["id"] for item in first["entries"]} & {item["id"] for item in second["entries"]})

    def test_mixed_page_has_constant_query_count_without_related_object_queries(self):
        self.receipt()
        self.receipt()
        self.historical()
        with self.assertNumQueries(4):
            result = inventory()
        self.assertEqual(len(result["entries"]), 3)
        self.assertEqual(self.inspect.call_count, 3)

    def test_compound_page_remains_readable_under_maintenance_on_each_database_backend(self):
        modern = self.receipt()
        legacy = self.historical()
        with CaptureQueriesContext(connection) as queries, read_only_database_access():
            result = inventory(page_size=1)
            second = inventory(page=2, page_size=1)
        self.assertTrue(result["available"])
        self.assertTrue(second["available"])
        self.assertEqual(result["entries"][0]["delivery_id"], legacy.pk)
        self.assertEqual(second["entries"][0]["id"], str(modern.pk))
        page_queries = [query["sql"] for query in queries if "storage_submission_page" in query["sql"]]
        self.assertEqual(len(page_queries), 2)
        self.assertTrue(all(query.startswith("SELECT * FROM (") for query in page_queries))

    def test_search_covers_product_release_unit_submitter_filename_and_uuid(self):
        receipt = self.receipt(filename="distinct-package.zip")
        for query in ("distinct-package", "test-product", "Test product", "test-release", "unit-1", "original-submitter", str(receipt.pk)):
            with self.subTest(query=query):
                self.assertEqual(inventory(query=query)["total"], 1)
        self.assertEqual(inventory(query="absent")["total"], 0)
        self.historical(filename="historical-search.zip")
        for query in ("historical-search", "historical-product", self.owner.username):
            with self.subTest(historical_query=query):
                self.assertEqual(inventory(query=query, status="historical")["total"], 1)

    def test_filtering_unfinished_publications_does_not_claim_they_are_ready_for_review(self):
        self.receipt(publication="pending")
        self.receipt(publication="publishing")
        self.receipt(publication="failed")
        self.assertEqual(inventory(status="pending")["total"], 0)
        preparing = inventory(status="publishing")
        self.assertEqual(preparing["total"], 2)
        self.assertFalse(any(item["location"]["available"] for item in preparing["entries"]))
        self.assertEqual(inventory(status="failed")["total"], 1)
        self.inspect.assert_not_called()

    def test_missing_or_changed_kind_does_not_hide_records_or_offer_a_download(self):
        self.receipt()
        for probe in (files.StorageError("Unavailable"), {"kind": "file"}):
            with self.subTest(probe=probe):
                if isinstance(probe, Exception):
                    self.inspect.side_effect = probe
                else:
                    self.inspect.side_effect = None
                    self.inspect.return_value = probe
                entry = inventory()["entries"][0]
                self.assertFalse(entry["location"]["available"])
                self.assertEqual(entry["location"]["label"], "Files unavailable")
                self.assertEqual(entry["download_url"], "")
                self.assertEqual(entry["files_url"], "")
                self.assertTrue(entry["record_url"].startswith("/admin/database/records/"))

    def test_deleted_owner_or_unsafe_historical_filename_cannot_select_another_location(self):
        self.historical(user=None)
        self.historical(filename="../outside.zip")
        result = inventory(status="historical")
        self.assertEqual(result["total"], 2)
        self.assertFalse(any(item["location"]["available"] for item in result["entries"]))
        self.inspect.assert_not_called()

    def test_parameter_bounds_empty_pages_and_database_failure_are_explanatory(self):
        self.receipt()
        result = inventory(page="invalid", page_size=1000, status="invalid", query=" " * 200)
        self.assertEqual(result["page_size"], 100)
        self.assertEqual(result["status"], "all")
        self.assertEqual(result["query"], "")
        self.assertEqual(inventory(page=999)["page"], 1)
        empty = inventory(query="absent")
        self.assertTrue(empty["available"])
        self.assertEqual(empty["entries"], [])
        with patch.object(DeliverySubmission.objects, "all", side_effect=DatabaseError("private database details")):
            unavailable = inventory()
        self.assertFalse(unavailable["available"])
        self.assertEqual(unavailable["entries"], [])
        self.assertNotIn("private database details", unavailable["message"])

    def test_storage_links_stay_inside_admin_and_publication_is_downloaded_as_retained_folder(self):
        receipt = self.receipt()
        entry = inventory()["entries"][0]
        self.assertEqual(entry["location"]["path"], receipt.artifact_key)
        self.assertIn("not been checked", entry["location"]["message"])
        self.assertEqual(urlsplit(entry["download_url"]).path, "/admin/storage/archive/")
        for key in ("record_url", "files_url", "download_url"):
            self.assertTrue(entry[key].startswith("/admin/"))

    def test_real_storage_probe_rejects_linked_retained_folders(self):
        receipt = self.receipt()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            published = root / "published"
            actual = root / "actual"
            actual.mkdir()
            published.mkdir()
            (published / "release").symlink_to(actual, target_is_directory=True)
            configuration = {
                "work_dir": str(root / "work"), "submission_dir": str(published),
                "boundary_dir": str(root / "boundaries"), "product_dirs": [],
            }
            with patch.object(files, "CONFIG", configuration), patch.object(files, "inspect_entry", wraps=_inspect_entry):
                entry = inventory()["entries"][0]
            self.assertFalse(entry["location"]["available"])
            self.assertEqual(entry["files_url"], "")
            self.assertEqual(entry["download_url"], "")
