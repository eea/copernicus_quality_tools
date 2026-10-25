"""One specification library keeps source URLs and QC selection compatible."""

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from qc_tool.common import CONFIG, QCException, load_product_definition, locate_product_definition
from qc_tool.frontend.dashboard.services import maintenance


class AdminSpecificationStorageTests(TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory(prefix="qc-specification-library-http-")))
        self.work = self.root / "work"
        self.uploads = self.work / "product_definitions"
        self.first_source = self.root / "first-source"
        self.second_source = self.root / "second-source"
        self.incoming = self.root / "incoming"
        self.boundaries = self.root / "boundaries"
        self.published = self.root / "published"
        for directory in (self.uploads, self.first_source, self.second_source,
                          self.incoming, self.boundaries, self.published):
            directory.mkdir(parents=True)
        self.enterContext(override_settings(
            MAINTENANCE_MODE=False, MEDIA_ROOT=str(self.incoming), QC_TOOL_STORAGE_ROOTS=[],
            QC_TOOL_MAINTENANCE_DIR=self.root / "maintenance",
            QC_TOOL_TRANSFER_DIR=self.root / "transfers",
            S3_CREDENTIALS_DIR=self.root / "credentials",
        ))
        self.enterContext(patch.dict(CONFIG, work_dir=self.work,
                                    product_dirs=[self.first_source, self.second_source],
                                    boundary_dir=self.boundaries, submission_dir=self.published,
                                    incoming_dir=self.incoming))
        administrator = get_user_model().objects.create_superuser(
            username="unified-specification-administrator", email="specifications@example.test",
            password="sufficient-test-password",
        )
        self.client.force_login(administrator)
        maintenance.read_status()

    @staticmethod
    def payload(description):
        # Formatting and non-ASCII bytes must survive the UI/download path.
        return ('{\n  "description": "' + description + '",\n  "steps": []\n}\n').encode("utf-8")

    def write_version(self, description, *, current=False, ident="example"):
        payload = self.payload(description)
        digest = sha256(payload).hexdigest()
        path = self.uploads / ".versions" / ident / (digest + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        if current:
            self.write_state(ident, {"active": True, "digest": digest})
        return digest, path, payload

    def write_state(self, ident, state):
        path = self.uploads / ".state" / (ident + ".json")
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")
        return path

    def library(self, **options):
        return self.client.get(reverse("admin_storage"), {"tab": "specifications", **options})

    def download(self, area, path):
        response = self.client.get(reverse("admin_storage_download"), {"area": area, "path": path})
        self.assertEqual(response.status_code, 200)
        self.assertIn("private", response["Cache-Control"])
        self.assertIn("no-store", response["Cache-Control"])
        return b"".join(response.streaming_content)

    def file_snapshot(self):
        return {path.relative_to(self.root): path.read_bytes()
                for source in (self.uploads, self.first_source, self.second_source)
                for path in source.rglob("*") if path.is_file() and not path.is_symlink()}

    def test_browse_files_keeps_saved_child_folders_and_installation_sources_separate(self):
        response = self.client.get(reverse("admin_storage"), {"tab": "files"})
        self.assertEqual(response.status_code, 200)
        locations = response.context["storage_locations"]
        self.assertNotIn("uploaded-specifications", {location["key"] for location in locations})
        self.assertFalse(any(location["collection"] == "specifications" for location in locations))
        work = next(location for location in locations if location["key"] == "work")
        contents = self.client.get(work["url"])
        self.assertIn("product_definitions", [row["name"] for row in contents.context["listing"]["entries"]])
        specification_locations = {location["key"]: location
                                   for location in response.context["storage_installation_locations"]}
        for area, source in (("spec-0", self.first_source), ("spec-1", self.second_source)):
            with self.subTest(area=area):
                location = specification_locations[area]
                self.assertEqual(location["label"], source.name)
                self.assertEqual(location["storage_path"], str(source))
                self.assertEqual(parse_qs(urlsplit(location["url"]).query),
                                 {"tab": ["files"], "area": [area]})
                opened = self.client.get(location["url"])
                self.assertEqual(opened.status_code, 200)
                self.assertEqual(opened.context["storage_tab"], "files")
                self.assertTrue(opened.context["storage_is_installation"])
        self.assertNotIn("jobs", {location["key"] for location in locations})
        library = self.library()
        self.assertContains(library, "<h1>Product specifications</h1>", html=True)

    def test_library_unifies_versioned_and_deployment_sources_without_changing_qc_selection(self):
        first_payload = self.payload("First deployment source")
        second_payload = self.payload("Second deployment source")
        (self.first_source / "example.json").write_bytes(first_payload)
        (self.second_source / "example.json").write_bytes(second_payload)
        old, _, old_payload = self.write_version("Previous specification")
        current, current_path, current_payload = self.write_version("Current specification – original", current=True)
        before = self.file_snapshot()

        normal = self.library(status="all")
        self.assertEqual(normal.status_code, 200)
        visible_versions = normal.context["library_listing"]["entries"]
        self.assertEqual({row["version_id"] for row in visible_versions}, {old, current})
        response = self.library(status="all", include_sources="1")

        self.assertEqual(response.status_code, 200)
        entries = response.context["library_listing"]["entries"]
        self.assertEqual(len(entries), 4)
        statuses = {row["version_id"]: row["status"] for row in entries}
        self.assertEqual(statuses[current], "current")
        self.assertEqual(statuses[old], "previous")
        self.assertEqual(sum(row["status"] == "current" for row in entries), 1)
        expected = {
            ("spec-0", "example.json"): first_payload,
            ("spec-1", "example.json"): second_payload,
            ("uploaded-specifications", ".versions/example/" + old + ".json"): old_payload,
            ("uploaded-specifications", ".versions/example/" + current + ".json"): current_payload,
        }
        for row in entries:
            with self.subTest(source=row["area"], version=row["version_id"]):
                download = self.client.get(row["download_url"])
                self.assertEqual(download.status_code, 200)
                self.assertEqual(b"".join(download.streaming_content), expected[(row["area"], row["path"])])
                detail = self.client.get(row["files_url"])
                self.assertEqual(detail.status_code, 200)
                self.assertEqual(parse_qs(urlsplit(detail.context["library_back_url"]).query).get("include_sources"), ["1"])
        self.assertEqual(locate_product_definition("example"), current_path)
        self.assertEqual(load_product_definition("example")["description"], "Current specification – original")
        self.assertEqual(self.file_snapshot(), before)

    def test_archived_versions_stay_downloadable_without_reactivating_an_old_source(self):
        (self.first_source / "example.json").write_bytes(self.payload("Deployment fallback"))
        digest, version, payload = self.write_version("Archived original", current=True)
        self.write_state("example", {"active": False})
        before = self.file_snapshot()

        response = self.library(status="all")

        self.assertEqual(response.status_code, 200)
        rows = response.context["library_listing"]["entries"]
        self.assertTrue(rows)
        self.assertTrue(all(row["status"] == "archived" for row in rows))
        row = next(row for row in rows if row["version_id"] == digest)
        download = self.client.get(row["download_url"])
        self.assertEqual(b"".join(download.streaming_content), payload)
        with self.assertRaisesRegex(QCException, "archived"):
            locate_product_definition("example")
        self.assertEqual(version.read_bytes(), payload)
        self.assertEqual(self.file_snapshot(), before)

    def test_installed_current_original_remains_visible_before_the_first_upload(self):
        first = self.first_source / "example.json"
        payload = self.payload("First configured original")
        first.write_bytes(payload)
        (self.second_source / "example.json").write_bytes(self.payload("Unused configured copy"))
        (self.uploads / "example.json").write_bytes(self.payload("Unused old uploaded copy"))
        before = self.file_snapshot()

        response = self.library(status="all")

        self.assertEqual(response.status_code, 200)
        rows = response.context["library_listing"]["entries"]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["area"], rows[0]["path"], rows[0]["status"]),
                         ("spec-0", "example.json", "current"))
        download = self.client.get(rows[0]["download_url"])
        self.assertEqual(b"".join(download.streaming_content), payload)
        self.assertEqual(locate_product_definition("example"), first)
        self.assertEqual(self.file_snapshot(), before)

    def test_old_direct_file_and_download_aliases_keep_exact_source_bytes(self):
        payload = self.payload("Unmodified deployment file")
        (self.first_source / "example.json").write_bytes(payload)
        digest, _, uploaded_payload = self.write_version("Unmodified uploaded file", current=True)
        for area, path, original in (
            ("spec-0", "example.json", payload),
            ("uploaded-specifications", ".versions/example/" + digest + ".json", uploaded_payload),
        ):
            with self.subTest(area=area):
                detail = self.client.get(reverse("admin_storage_file"), {"area": area, "path": path})
                self.assertEqual(detail.status_code, 200)
                self.assertFalse(detail.context["review"]["can_quarantine"])
                self.assertEqual(self.download(area, path), original)
                self.assertEqual(self.client.get(reverse("admin_storage_trash"), {"area": area}).status_code, 404)

    def test_source_root_links_open_the_real_folder_without_redirecting_to_versions(self):
        self.write_version("Retained current specification", current=True)
        for area in ("uploaded-specifications", "spec-0", "spec-1"):
            with self.subTest(area=area):
                response = self.client.get(reverse("admin_storage"), {"area": area})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["storage_tab"], "files")
                self.assertEqual(response.context["listing"]["area"], area)
                self.assertNotIn("library_listing", response.context)
        uploaded = self.client.get(reverse("admin_storage"), {"area": "uploaded-specifications"})
        self.assertEqual([row["name"] for row in uploaded.context["listing"]["entries"]], [".versions"])

    def test_historical_aliases_cannot_expose_control_markers_or_follow_symlinks(self):
        digest, _, _ = self.write_version("Current", current=True)
        external = self.root / "private-original.json"
        external.write_bytes(b"private external source")
        (self.first_source / "linked.json").symlink_to(external)
        for area, path in (
            ("uploaded-specifications", ".state/example.json"),
            ("uploaded-specifications", ".versions/example/../" + digest + ".json"),
            ("spec-0", "../private-original.json"),
            ("spec-0", "linked.json"),
        ):
            for route in ("admin_storage_file", "admin_storage_download"):
                with self.subTest(area=area, path=path, route=route):
                    response = self.client.get(reverse(route), {"area": area, "path": path})
                    self.assertIn(response.status_code, (400, 404, 409))
                    self.assertNotContains(response, "private external source", status_code=response.status_code)

    def test_missing_configured_source_does_not_crash_or_hide_retained_current_version(self):
        digest, path, payload = self.write_version("Available current version", current=True)
        self.second_source.rmdir()

        response = self.library(status="all")

        self.assertEqual(response.status_code, 200)
        rows = response.context["library_listing"]["entries"]
        row = next(row for row in rows if row["version_id"] == digest)
        self.assertEqual(row["status"], "current")
        download = self.client.get(row["download_url"])
        self.assertEqual(b"".join(download.streaming_content), payload)
        self.assertEqual(locate_product_definition("example"), path)
