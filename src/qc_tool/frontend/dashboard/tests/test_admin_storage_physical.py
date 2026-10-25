"""Filesystem browsing keeps real paths and a reliable way back to each folder."""

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from zipfile import ZipFile

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from qc_tool.common import CONFIG
from qc_tool.frontend.dashboard.services import maintenance


class AdminPhysicalStorageTests(TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory(prefix="qc-physical-browser-http-")))
        self.work = self.root / "work"
        self.uploads = self.work / "product_definitions"
        self.specifications = self.root / "installation" / "product_definitions"
        self.incoming = self.root / "incoming"
        self.boundaries = self.root / "boundaries"
        self.published = self.root / "submission"
        for directory in (self.uploads, self.specifications, self.incoming,
                          self.boundaries, self.published):
            directory.mkdir(parents=True)
        self.enterContext(override_settings(
            MAINTENANCE_MODE=False, MEDIA_ROOT=str(self.incoming), QC_TOOL_STORAGE_ROOTS=[],
            QC_TOOL_MAINTENANCE_DIR=self.root / "maintenance",
            QC_TOOL_TRANSFER_DIR=self.root / "transfers",
            S3_CREDENTIALS_DIR=self.root / "credentials",
        ))
        self.enterContext(patch.dict(CONFIG, work_dir=self.work, product_dirs=[self.specifications],
                                    boundary_dir=self.boundaries, submission_dir=self.published,
                                    incoming_dir=self.incoming))
        administrator = get_user_model().objects.create_superuser(
            username="physical-storage-administrator", email="physical-storage@example.test",
            password="sufficient-test-password",
        )
        self.client.force_login(administrator)
        maintenance.read_status()

    @staticmethod
    def query(url):
        return parse_qs(urlsplit(url).query)

    def browse(self, area="work", path="", **options):
        return self.client.get(reverse("admin_storage"), {"tab": "files", "area": area,
                                                          "path": path, **options})

    def write_original(self):
        payload = b'{\n  "description": "Original bytes",\n  "steps": []\n}\n'
        digest = sha256(payload).hexdigest()
        relative = ".versions/example/" + digest + ".json"
        original = self.uploads / relative
        original.parent.mkdir(parents=True)
        original.write_bytes(payload)
        return relative, original, payload

    def test_normal_locations_show_each_storage_tree_once_and_keep_installation_sources_accessible(self):
        response = self.client.get(reverse("admin_storage"), {"tab": "files"})
        self.assertEqual(response.status_code, 200)
        locations = {row["key"]: row for row in response.context["storage_locations"]}
        self.assertNotIn("jobs", locations)
        self.assertNotIn("uploaded-specifications", locations)
        self.assertNotIn("spec-0", locations)
        installation = {row["key"]: row for row in response.context["storage_installation_locations"]}
        for area, directory in (("work", self.work), ("spec-0", self.specifications)):
            with self.subTest(area=area):
                location = (installation if area == "spec-0" else locations)[area]
                self.assertEqual(location["label"], directory.name)
                self.assertEqual(location["storage_path"], str(directory))
                self.assertEqual(self.query(location["url"]), {"tab": ["files"], "area": [area]})
                self.assertContains(response, str(directory))
        contents = self.client.get(locations["work"]["url"])
        self.assertIn("product_definitions", [row["name"] for row in contents.context["listing"]["entries"]])
        self.assertFalse(response.context["storage_is_installation"])
        installed = self.client.get(installation["spec-0"]["url"])
        self.assertTrue(installed.context["storage_is_installation"])
        self.assertContains(installed, 'class="storage-sidebar__installation" open')

    def test_walk_original_versions_through_work_tree_with_physical_breadcrumbs(self):
        relative, original, payload = self.write_original()
        expected_path = "product_definitions/" + relative
        location = ""
        for name in ("product_definitions", ".versions", "example"):
            response = self.browse(path=location)
            self.assertEqual(response.status_code, 200)
            row = next(row for row in response.context["listing"]["entries"] if row["name"] == name)
            self.assertEqual(row["kind"], "directory")
            self.assertEqual(self.query(row["url"])["tab"], ["files"])
            response = self.client.get(row["url"])
            self.assertEqual(response.status_code, 200)
            location = row["path"]
        self.assertEqual(response.context["storage_path"], str(original.parent))
        self.assertEqual([crumb["label"] for crumb in response.context["crumbs"]][-4:],
                         ["work", "product_definitions", ".versions", "example"])
        self.assertEqual(response.context["storage_tab"], "files")
        row = response.context["listing"]["entries"][0]
        self.assertEqual(row["path"], expected_path)
        detail = self.client.get(row["url"])
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.context["storage_tab"], "files")
        self.assertEqual(detail.context["title"], original.name)
        self.assertFalse(detail.context["review"]["can_quarantine"])
        downloaded = self.client.get(detail.context["download_url"])
        self.assertEqual(b"".join(downloaded.streaming_content), payload)
        self.assertEqual(original.read_bytes(), payload)

    def test_file_details_return_to_the_same_search_sort_and_page(self):
        folder = self.work / "reports"
        folder.mkdir()
        for index in range(56):
            (folder / f"result-{index:02d}.txt").write_bytes(b"result" + b"!" * index)
        response = self.browse(path="reports", q="result", sort="size", direction="desc", page="2")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["listing"]["page"], 2)
        row = response.context["listing"]["entries"][0]
        options = self.query(row["url"])
        for key, value in {"browser": "files", "browse_query": "result", "browse_sort": "size",
                           "browse_direction": "desc", "browse_page": "2"}.items():
            self.assertEqual(options[key], [value])
        detail = self.client.get(row["url"])
        self.assertEqual(detail.status_code, 200)
        parent_options = self.query(detail.context["parent_url"])
        for key, value in {
            "tab": ["files"], "area": ["work"], "path": ["reports"],
            "q": ["result"], "sort": ["size"], "direction": ["desc"], "page": ["2"],
        }.items():
            self.assertEqual(parent_options[key], value)
        self.assertNotIn("library", parent_options)
        returned = self.client.get(detail.context["parent_url"])
        self.assertEqual(returned.status_code, 200)
        self.assertEqual([entry["path"] for entry in returned.context["listing"]["entries"]],
                         [entry["path"] for entry in response.context["listing"]["entries"]])
        for name in ("download_url", "verify_url"):
            self.assertEqual(self.query(detail.context[name])["browser"], ["files"])
            self.assertEqual(self.query(detail.context[name])["browse_page"], ["2"])

    def test_new_folder_and_up_navigation_clear_local_search_and_page_but_keep_sort(self):
        folder = self.work / "reports" / "matching-child"
        folder.mkdir(parents=True)
        (folder / "does-not-match.txt").write_bytes(b"inside child")
        response = self.browse(path="reports", q="matching", sort="modified", direction="desc", page="9")
        self.assertEqual(response.status_code, 200)
        row = response.context["listing"]["entries"][0]
        options = self.query(row["url"])
        self.assertNotIn("q", options)
        self.assertNotIn("page", options)
        self.assertEqual(options["sort"], ["modified"])
        self.assertEqual(options["direction"], ["desc"])
        opened = self.client.get(row["url"])
        self.assertEqual(opened.status_code, 200)
        self.assertEqual(opened.context["listing"]["entries"][0]["name"], "does-not-match.txt")
        for destination in (opened.context["parent_url"], opened.context["crumbs"][-2]["url"]):
            options = self.query(destination)
            self.assertNotIn("q", options)
            self.assertNotIn("page", options)
            self.assertEqual(options["sort"], ["modified"])
            self.assertEqual(options["direction"], ["desc"])

    def test_bare_specification_aliases_stay_physical_and_explicit_library_stays_logical(self):
        relative, _original, payload = self.write_original()
        (self.specifications / "example.json").write_bytes(payload)
        for area, path in (("uploaded-specifications", relative), ("spec-0", "example.json")):
            with self.subTest(area=area):
                physical = self.client.get(reverse("admin_storage_file"), {"area": area, "path": path})
                self.assertEqual(physical.status_code, 200)
                self.assertEqual(physical.context["storage_tab"], "files")
                self.assertFalse(physical.context["library_back_url"])
                self.assertEqual(self.query(physical.context["parent_url"])["tab"], ["files"])
                logical = self.client.get(reverse("admin_storage_file"), {
                    "area": area, "path": path, "library": "specifications", "library_status": "all",
                })
                self.assertEqual(logical.status_code, 200)
                self.assertEqual(logical.context["storage_tab"], "specifications")
                self.assertEqual(self.query(logical.context["parent_url"]),
                                 {"tab": ["history"], "collection": ["specifications"], "status": ["all"]})

    def test_work_version_folder_zip_contains_original_paths_and_bytes(self):
        relative, original, payload = self.write_original()
        listed = self.browse(path="product_definitions")
        row = next(row for row in listed.context["listing"]["entries"] if row["name"] == ".versions")
        response = self.client.get(row["download_url"])
        self.assertEqual(response.status_code, 200)
        with ZipFile(BytesIO(b"".join(response.streaming_content))) as archive:
            self.assertEqual(archive.read("files/product_definitions/" + relative), payload)
        self.assertEqual(original.read_bytes(), payload)

    def test_configured_roots_and_missing_mounts_have_recoverable_physical_pages(self):
        shared = self.root / "shared"
        shared.mkdir()
        (shared / "readme.txt").write_bytes(b"mounted original")
        missing = self.root / "not-mounted"
        with override_settings(QC_TOOL_STORAGE_ROOTS=[
            {"key": "shared", "label": "Shared archive", "path": str(shared)},
            {"key": "missing", "label": "Offline archive", "path": str(missing)},
        ]):
            home = self.client.get(reverse("admin_storage"), {"tab": "files"})
            self.assertEqual(home.status_code, 200)
            locations = {row["key"]: row for row in home.context["storage_locations"]}
            self.assertTrue(locations["extra-shared"]["available"])
            self.assertFalse(locations["extra-missing"]["available"])
            opened = self.client.get(locations["extra-shared"]["url"])
            self.assertEqual(opened.status_code, 200)
            self.assertEqual(opened.context["storage_path"], str(shared))
            self.assertEqual(opened.context["listing"]["entries"][0]["name"], "readme.txt")
            unavailable = self.client.get(locations["extra-missing"]["url"])
            self.assertIn(unavailable.status_code, (404, 409, 503))
            self.assertTrue(unavailable.context["storage_error"])
            self.assertContains(unavailable, reverse("admin_storage"), status_code=unavailable.status_code)

    def test_nested_reference_browsing_never_exposes_private_markers_or_link_targets(self):
        self.write_original()
        state = self.uploads / ".state"
        state.mkdir()
        (state / "example.json").write_bytes(b"private activation state")
        (self.work / "worker.token").write_bytes(b"private worker token")
        outside = self.root / "outside-secret.json"
        outside.write_bytes(b"outside secret")
        (self.uploads / "linked.json").symlink_to(outside)
        listed = self.browse(path="product_definitions")
        self.assertEqual(listed.status_code, 200)
        names = {entry["name"] for entry in listed.context["listing"]["entries"]}
        self.assertIn(".versions", names)
        self.assertNotIn(".state", names)
        self.assertNotIn("linked.json", names)
        for path in ("product_definitions/.state/example.json", "product_definitions/linked.json",
                     "worker.token", "product_definitions/../../outside-secret.json"):
            for route in ("admin_storage_file", "admin_storage_download"):
                with self.subTest(path=path, route=route):
                    response = self.client.get(reverse(route), {"area": "work", "path": path, "browser": "files"})
                    self.assertIn(response.status_code, (400, 404, 409))
                    for secret in ("private activation state", "private worker token", "outside secret"):
                        self.assertNotContains(response, secret, status_code=response.status_code)
