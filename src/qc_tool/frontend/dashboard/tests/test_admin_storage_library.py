"""Admin storage libraries retain existing version and approval authorities."""

from hashlib import sha256
from html.parser import HTMLParser
from io import BytesIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
from zipfile import ZipFile

from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from qc_tool.common import CONFIG
from qc_tool.frontend.dashboard.models import (
    Delivery, DeliverySubmission, Job, Product, ProductRelease, ProductReleaseDefinition,
    ProductUnit, QcDefinition,
)
from qc_tool.frontend.dashboard.services import maintenance
from qc_tool.frontend.dashboard.services.storage_admin.navigation import LIBRARIES


class Links(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.anchors = []
        self.forms = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "a" and "href" in values:
            self.anchors.append(values["href"])
        if tag == "form":
            self.forms.append(values)


class AdminStorageLibraryTests(TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory(prefix="qc-storage-library-http-")))
        self.work = self.root / "work"
        self.uploaded = self.work / "product_definitions"
        self.boundaries = self.root / "boundaries"
        self.deployment = self.root / "deployment"
        self.published = self.root / "published"
        self.incoming = self.root / "incoming"
        for root in (self.uploaded, self.boundaries, self.deployment, self.published, self.incoming):
            root.mkdir(parents=True)
        self.enterContext(override_settings(
            MAINTENANCE_MODE=False, MEDIA_ROOT=str(self.incoming), QC_TOOL_STORAGE_ROOTS=[],
            QC_TOOL_MAINTENANCE_DIR=self.root / "maintenance",
            QC_TOOL_TRANSFER_DIR=self.root / "transfers", S3_CREDENTIALS_DIR=self.root / "credentials",
        ))
        self.enterContext(patch.dict(CONFIG, work_dir=self.work, incoming_dir=self.incoming,
                                    submission_dir=self.published, boundary_dir=self.boundaries,
                                    product_dirs=[self.deployment]))
        self.administrator = get_user_model().objects.create_superuser(
            username="library-administrator", password="sufficient-test-password",
            email="library@example.test",
        )
        self.owner = get_user_model().objects.create_user(username="library-uploader")
        self.client.force_login(self.administrator)
        self.product = Product.objects.create(ident="test-product", name="Test product")
        self.release = ProductRelease.objects.create(
            product=self.product, release_key="test-plan", revision=1,
            description="Test plan", catalog_digest="a" * 64, is_current=True,
        )
        self.sequence = 0
        maintenance.read_status()

    def receipt(self, *, review="pending", publication="published", filename=None, available=True):
        self.sequence += 1
        delivery = Delivery.objects.create(
            user=self.owner, filename=filename or f"delivery-{self.sequence}.zip", size_bytes=12,
            product_ident=self.product.ident, product_description=self.product.name,
            date_submitted=timezone.now() if publication == "published" else None,
        )
        job = Job.objects.create(delivery=delivery, product_ident=self.product.ident,
                                 product_description=self.product.name)
        unit = ProductUnit.objects.create(product_release=self.release,
                                          product_unit_code=f"unit-{self.sequence}", provenance="test")
        artifact_key = (f"release-{self.release.pk}-test-plan/product-unit-{unit.pk}-{unit.product_unit_code}/"
                        f"submission-{uuid4()}.d")
        receipt = DeliverySubmission.objects.create(
            delivery=delivery, job=job, product_release=self.release, product_unit=unit,
            product_unit_code=unit.product_unit_code, verified_product_unit_code=unit.product_unit_code,
            submitted_by=self.owner, submitted_by_username="Original submitter", request_channel="browser",
            publication_state=publication, review_state=review,
            published_at=timezone.now() if publication == "published" else None,
            artifact_key=artifact_key if publication == "published" else "",
            artifact_digest="b" * 64 if publication == "published" else "",
            input_digest="c" * 64 if publication == "published" else "",
        )
        if available and publication == "published":
            output = self.published / artifact_key / "output.d"
            output.mkdir(parents=True)
            (output / "notes.txt").write_bytes(b"retained original bytes\n")
        return receipt

    def specification(self, payload=b'{ "original": true }\n', *, ident="test-product", current=False, archived=False):
        digest = sha256(payload).hexdigest()
        directory = self.uploaded / ".versions" / ident
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (digest + ".json")
        path.write_bytes(payload)
        if current or archived:
            states = self.uploaded / ".state"
            states.mkdir(exist_ok=True)
            (states / (ident + ".json")).write_text(json.dumps({"active": not archived, "digest": digest}))
        return digest, path

    def generation(self, number, *, current=False):
        ident = "gen-" + f"{number:032x}"
        directory = self.boundaries / ".boundary-generations" / ident
        for kind in ("raster", "vector"):
            (directory / kind).mkdir(parents=True)
            (directory / kind / "original.txt").write_bytes(b"original boundary\n")
        if current:
            (self.boundaries / ".boundary-current").symlink_to(".boundary-generations/" + ident)
        return ident

    def library(self, tab=None, **options):
        return self.client.get(reverse("admin_storage"), {**({"tab": tab} if tab else {}), **options})

    @staticmethod
    def query(url):
        return parse_qs(urlsplit(url).query)

    def assert_private(self, response):
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("private", response["Cache-Control"])

    def test_root_defaults_to_submitted_deliveries_and_separates_approval_from_stored_files(self):
        pending = self.receipt(filename="awaiting-decision.zip")
        approved = self.receipt(review="accepted", filename="approved-delivery.zip")
        self.receipt(publication="failed", filename="failed-publication.zip")
        Delivery.objects.create(user=self.owner, filename="unsubmitted-upload.zip", size_bytes=1)
        response = self.library()
        self.assertContains(response, "<h1>Submitted deliveries</h1>", html=True)
        self.assertContains(response, "Awaiting review")
        self.assertContains(response, "Approved")
        self.assertNotContains(response, "unsubmitted-upload.zip")
        self.assertEqual(response.context["storage_tab"], "deliveries")
        self.assertEqual(response.context["library_listing"]["total"], 3)
        entries = {row["id"]: row for row in response.context["library_listing"]["entries"]}
        self.assertFalse(entries[str(pending.pk)]["is_approved"])
        self.assertTrue(entries[str(approved.pk)]["is_approved"])
        self.assert_private(response)
        self.assertEqual(self.library("invalid-tab").context["storage_tab"], "deliveries")

    def test_delivery_links_open_exact_retained_files_and_download_original_zip_members(self):
        receipt = self.receipt(review="accepted")
        response = self.library()
        entry = response.context["library_listing"]["entries"][0]
        self.assertEqual(self.query(entry["files_url"]), {
            "area": ["published"], "path": [receipt.artifact_key], "library": ["deliveries"],
            "library_status": ["all"],
        })
        self.assertTrue(urlsplit(entry["record_url"]).path.startswith("/admin/database/"))
        opened = self.client.get(entry["files_url"])
        self.assertContains(opened, "Back to submitted deliveries")
        self.assertContains(opened, "<h1>Submitted delivery files</h1>", html=True)
        self.assertIn("Submitted delivery files", [crumb["label"] for crumb in opened.context["crumbs"]])
        self.assertNotIn(receipt.artifact_key.rsplit("/", 1)[-1],
                         [crumb["label"] for crumb in opened.context["crumbs"]])
        self.assertEqual(opened.context["parent_url"], opened.context["library_back_url"])
        download = self.client.get(entry["download_url"])
        self.assertEqual(download.status_code, 200)
        with ZipFile(BytesIO(b"".join(download.streaming_content))) as archive:
            self.assertEqual(archive.read("files/" + receipt.artifact_key + "/output.d/notes.txt"),
                             b"retained original bytes\n")
        self.assert_private(download)

    def test_unavailable_files_do_not_hide_approved_records_or_offer_downloads(self):
        self.receipt(review="accepted", filename="missing-evidence.zip", available=False)
        response = self.library(status="approved")
        self.assertContains(response, "missing-evidence.zip")
        self.assertContains(response, "Files unavailable")
        row = response.context["library_listing"]["entries"][0]
        self.assertTrue(row["is_approved"])
        self.assertEqual((row["files_url"], row["download_url"]), ("", ""))

    def test_delivery_search_filters_and_pagination_preserve_user_choices(self):
        for number in range(27):
            self.receipt(review="accepted", filename=f"regional-batch-{number}.zip", available=False)
        self.receipt(filename="awaiting-special.zip", available=False)
        first = self.library(status="approved", q="regional-batch")
        listing = first.context["library_listing"]
        self.assertEqual((listing["total"], len(listing["entries"])), (27, 25))
        next_url = first.context["library_next_url"]
        self.assertEqual(self.query(next_url), {"tab": ["deliveries"], "status": ["approved"],
                                               "q": ["regional-batch"], "page": ["2"]})
        second = self.client.get(next_url)
        self.assertEqual(len(second.context["library_listing"]["entries"]), 2)
        self.assertNotContains(second, "awaiting-special.zip")
        pending = self.library(status="pending", q="special")
        self.assertEqual(pending.context["library_listing"]["total"], 1)
        self.assertContains(self.library(q="absent-query"), "No submissions match these filters")

    def test_specification_versions_show_readable_statuses_and_download_exact_original_bytes(self):
        old, _ = self.specification(b'{ "previous": true }\n')
        payload = b'{\n  "original": true, "description": "Original bytes"\n}\n'
        current, _ = self.specification(payload, current=True)
        definition = QcDefinition.objects.create(product_ident="test-product", digest=current,
            description="Original bytes", document={"original": True}, source_path="upload:test-product.json")
        ProductReleaseDefinition.objects.create(product_release=self.release, qc_definition=definition, is_primary=True)
        response = self.library("specifications", status="all")
        self.assertContains(response, "<h1>Product specifications</h1>", html=True)
        self.assertContains(response, "Current")
        self.assertContains(response, "Previous")
        self.assertContains(response, "Download original")
        entries = {row["version_id"]: row for row in response.context["library_listing"]["entries"]}
        self.assertEqual(entries[old]["status"], "previous")
        row = entries[current]
        self.assertIn("Revision 1", row["version_label"])
        self.assertEqual(self.query(row["download_url"])["library"], ["specifications"])
        downloaded = self.client.get(row["download_url"])
        self.assertEqual(b"".join(downloaded.streaming_content), payload)
        info = self.client.get(row["files_url"])
        self.assertContains(info, "Back to product specifications")
        self.assertContains(info, "<h1>Specification file</h1>", html=True)
        self.assertNotIn(".versions", [crumb["label"] for crumb in info.context["crumbs"]])
        self.assert_private(info)

    def test_specification_search_status_filter_and_page_links_keep_context(self):
        for number in range(52):
            self.specification(f'{{"revision": {number}}}\n'.encode())
        response = self.library("specifications", q="test-product", status="previous")
        self.assertEqual(response.context["library_listing"]["total"], 52)
        self.assertEqual(len(response.context["library_listing"]["entries"]), 50)
        self.assertEqual(self.query(response.context["library_next_url"]), {
            "tab": ["specifications"], "q": ["test-product"], "status": ["previous"], "page": ["2"],
        })
        second = self.client.get(response.context["library_next_url"])
        self.assertEqual(len(second.context["library_listing"]["entries"]), 2)
        detail_url = second.context["library_listing"]["entries"][0]["files_url"]
        expected_return = {"library": ["specifications"], "library_query": ["test-product"],
                           "library_status": ["previous"], "library_page": ["2"]}
        for key, value in expected_return.items():
            self.assertEqual(self.query(detail_url)[key], value)
        detail = self.client.get(detail_url)
        expected_library = {"tab": ["specifications"], "q": ["test-product"],
                            "status": ["previous"], "page": ["2"]}
        self.assertEqual(self.query(detail.context["library_back_url"]), expected_library)
        self.assertEqual(self.query(detail.context["parent_url"]), expected_library)
        for field in ("download_url", "verify_url"):
            for key, value in expected_return.items():
                self.assertEqual(self.query(detail.context[field])[key], value)
        self.assertContains(detail, 'name="library_query" value="test-product"')
        self.assertContains(detail, 'name="library_status" value="previous"')
        self.assertContains(detail, 'name="library_page" value="2"')
        checked = self.client.get(detail.context["verify_url"])
        self.assertEqual(checked.status_code, 200)
        self.assertEqual(self.query(checked.context["library_back_url"]), expected_library)
        returned = self.client.get(checked.context["library_back_url"])
        self.assertEqual(returned.context["library_listing"]["page"], 2)
        self.assertEqual(returned.context["status"], "previous")
        self.assertEqual(returned.context["query"], "test-product")
        self.assertContains(self.library("specifications", q="no-such-product"), "No versions match these filters")

    def test_reference_libraries_start_with_current_versions_and_offer_product_history(self):
        previous, _ = self.specification(b'{ "previous": true }\n')
        current, _ = self.specification(current=True)
        self.specification(ident="archived-product", archived=True)
        self.generation(1)
        selected_boundary = self.generation(2, current=True)
        specifications = self.library("specifications")
        self.assertEqual(specifications.context["status"], "current")
        entry, = specifications.context["library_listing"]["entries"]
        self.assertEqual(entry["version_id"], current)
        self.assertEqual(self.query(entry["history_url"]), {
            "tab": ["specifications"], "q": ["test-product"], "status": ["all"],
        })
        self.assertContains(specifications, 'aria-label="Version history for Test product"')
        history = self.client.get(entry["history_url"])
        self.assertEqual({row["version_id"] for row in history.context["library_listing"]["entries"]},
                         {current, previous})
        boundaries = self.library("boundaries")
        self.assertEqual(boundaries.context["status"], "current")
        self.assertEqual([row["version_id"] for row in boundaries.context["library_listing"]["entries"]],
                         [selected_boundary])

    def test_boundary_versions_show_current_and_previous_with_exact_folder_zip_selection(self):
        previous = self.generation(1)
        current = self.generation(2, current=True)
        response = self.library("boundaries", status="all")
        self.assertContains(response, "<h1>Boundary versions</h1>", html=True)
        entries = {row["version_id"]: row for row in response.context["library_listing"]["entries"]}
        self.assertEqual(entries[previous]["status"], "previous")
        self.assertEqual(entries[current]["status"], "current")
        query = self.query(entries[current]["download_url"])
        self.assertEqual(query["selection"], ["1"])
        self.assertEqual(query["paths"], [".boundary-generations/" + current])
        self.assertEqual(query["library"], ["boundaries"])
        opened = self.client.get(entries[current]["files_url"])
        self.assertContains(opened, "<h1>Boundary package files</h1>", html=True)
        crumb_labels = [crumb["label"] for crumb in opened.context["crumbs"]]
        self.assertIn("Boundary package files", crumb_labels)
        self.assertNotIn(".boundary-generations", crumb_labels)
        self.assertNotIn(current, crumb_labels)
        self.assertEqual(opened.context["parent_url"], opened.context["library_back_url"])
        raw = self.library(area="boundaries", path=".boundary-generations/" + current)
        self.assertContains(raw, "<h1>" + current + "</h1>", html=True)
        self.assertIn(current, [crumb["label"] for crumb in raw.context["crumbs"]])
        downloaded = self.client.get(entries[current]["download_url"])
        with ZipFile(BytesIO(b"".join(downloaded.streaming_content))) as archive:
            names = archive.namelist()
            self.assertTrue(any(current in name for name in names))
            self.assertFalse(any(previous in name for name in names))
        self.assert_private(downloaded)

    def test_unmanaged_boundary_download_selects_only_raster_and_vector_excluding_retained_history(self):
        for kind in ("raster", "vector"):
            (self.boundaries / kind).mkdir()
            (self.boundaries / kind / "live.txt").write_bytes(b"original installation boundary")
        previous = self.generation(7)
        response = self.library("boundaries", status="current")
        entry, = response.context["library_listing"]["entries"]
        self.assertEqual(entry["version_id"], "legacy-unmanaged")
        self.assertEqual(self.query(entry["download_url"])["paths"], ["raster", "vector"])
        downloaded = self.client.get(entry["download_url"])
        with ZipFile(BytesIO(b"".join(downloaded.streaming_content))) as archive:
            names = archive.namelist()
            self.assertIn("files/raster/live.txt", names)
            self.assertIn("files/vector/live.txt", names)
            self.assertFalse(any(previous in name or ".boundary-generations" in name for name in names))

    def test_corrupt_boundary_selection_explains_unknown_state_without_activating_history(self):
        self.generation(3)
        (self.boundaries / ".boundary-current").symlink_to("../../private")
        response = self.library("boundaries", status="all")
        self.assertContains(response, "activation pointer is invalid")
        self.assertTrue(response.context["library_listing"]["warnings"])
        self.assertFalse(any(entry["status"] == "current" for entry in response.context["library_listing"]["entries"]))
        self.assertEqual(os.readlink(self.boundaries / ".boundary-current"), "../../private")

    def test_nested_browser_and_file_navigation_preserve_allowed_library_return_context(self):
        receipt = self.receipt()
        response = self.library()
        folder = self.client.get(response.context["library_listing"]["entries"][0]["files_url"])
        self.assertEqual(folder.context["storage_library"], "deliveries")
        self.assertEqual(folder.context["parent_url"], folder.context["library_back_url"])
        for field in ("refresh_url", "sort_name_url", "archive_url", "clear_search_url"):
            self.assertEqual(self.query(folder.context[field])["library"], ["deliveries"])
        child = self.client.get(folder.context["listing"]["entries"][0]["url"])
        self.assertEqual(self.query(child.context["listing"]["entries"][0]["url"])["library"], ["deliveries"])
        detail = self.client.get(child.context["listing"]["entries"][0]["url"])
        self.assertEqual(detail.context["storage_tab"], "deliveries")
        self.assertEqual(self.query(detail.context["parent_url"])["path"], [receipt.artifact_key + "/output.d"])
        for field in ("download_url", "verify_url", "parent_url"):
            self.assertEqual(self.query(detail.context[field])["library"], ["deliveries"])
        self.assertContains(detail, 'name="library" value="deliveries"')
        self.assertEqual(self.query(detail.context["library_back_url"]), {"tab": ["deliveries"], "status": ["all"]})

    def test_invalid_library_context_is_discarded_and_cannot_create_an_external_return_link(self):
        receipt = self.receipt()
        for invalid in ("https://outside.example/", "../../workspace", "connection", "not-a-library"):
            with self.subTest(value=invalid):
                response = self.library(area="published", path=receipt.artifact_key, library=invalid)
                self.assertEqual(response.context["storage_library"], "")
                self.assertEqual(response.context["library_back_url"], "")
                self.assertEqual(response.context["storage_tab"], "files")
                self.assertNotIn("library", self.query(response.context["refresh_url"]))

    def test_library_return_parameters_are_bounded_and_unknown_values_are_discarded(self):
        receipt = self.receipt()
        response = self.library(area="published", path=receipt.artifact_key,
            library="specifications", library_query="x" * 300, library_status="https://outside.example/",
            library_page="1000001")
        self.assertEqual(response.context["storage_return_context"], {
            "library": "specifications", "library_query": "x" * 150,
        })
        self.assertEqual(self.query(response.context["library_back_url"]), {
            "tab": ["specifications"], "q": ["x" * 150],
        })
        for page in ("not-a-page", "-5", "0"):
            with self.subTest(page=page):
                bounded = self.library(area="published", path=receipt.artifact_key,
                    library="deliveries", library_status="approved", library_page=page)
                self.assertEqual(bounded.context["storage_return_context"], {
                    "library": "deliveries", "library_status": "approved",
                })

    def test_library_routes_are_admin_only_get_only_and_offer_no_workspace_workflow_actions(self):
        self.receipt()
        for tab in LIBRARIES:
            with self.subTest(tab=tab):
                response = self.library(tab)
                self.assert_private(response)
                self.assertEqual(self.client.post(reverse("admin_storage"), {"tab": tab}).status_code, 405)
                parser = Links(response.content.decode())
                forbidden_paths = {reverse(route) for route in (
                    "product_upload", "boundaries_upload", "submission_queue", "file_upload",
                )}
                self.assertFalse(forbidden_paths & {urlsplit(address).path for address in parser.anchors})
                self.assertFalse(any(form.get("method", "get").lower() == "post" and
                    "/storage/" in form.get("action", "") for form in parser.forms))
        self.client.logout()
        response = self.library("specifications")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlsplit(response["Location"]).path, reverse("admin_login"))
        get_user_model().objects.filter(pk=self.owner.pk).update(is_staff=True)
        self.owner.refresh_from_db()
        self.client.force_login(self.owner)
        self.assertEqual(self.library("deliveries").status_code, 403)

    def test_database_failure_keeps_reference_files_browsable_without_exposing_private_details(self):
        self.specification(current=True)
        with patch.object(DeliverySubmission.objects, "all", side_effect=DatabaseError("private database credentials")):
            response = self.library()
        self.assertContains(response, "This library is temporarily unavailable")
        self.assertNotContains(response, "private database credentials")
        self.assertContains(response, "Browse stored files")

    @override_settings(SESSION_SAVE_EVERY_REQUEST=True)
    def test_libraries_and_original_downloads_are_read_only_during_ready_maintenance(self):
        self.receipt()
        self.specification(current=True)
        self.generation(9, current=True)
        state = maintenance.read_status()
        state = maintenance.enable(self.administrator, state["generation"])
        state = maintenance.advance(state["generation"])
        self.assertEqual(state["phase"], "ready")

        def snapshot():
            result = {}
            for path in self.root.rglob("*"):
                value = path.lstat()
                result[path.relative_to(self.root).as_posix()] = (
                    value.st_mode, value.st_ino, value.st_size, value.st_mtime_ns,
                    os.readlink(path) if path.is_symlink() else sha256(path.read_bytes()).hexdigest() if path.is_file() else "",
                )
            return result

        before = snapshot()
        with CaptureQueriesContext(connection) as captured:
            for tab in LIBRARIES:
                response = self.library(tab)
                self.assertEqual(response.status_code, 200)
                for entry in response.context["library_listing"]["entries"]:
                    if entry.get("download_url"):
                        downloaded = self.client.get(entry["download_url"])
                        self.assertEqual(downloaded.status_code, 200)
                        b"".join(downloaded.streaming_content)
        writes = [item["sql"] for item in captured if item["sql"].lstrip().upper().startswith(
            ("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER ", "DROP "))]
        self.assertEqual(writes, [])
        self.assertEqual(snapshot(), before)
