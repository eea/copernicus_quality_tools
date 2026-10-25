"""The production persistent tree is browsable without exposing private state."""

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


class AdminPersistentStorageTests(TestCase):
    def setUp(self):
        self.host = Path(self.enterContext(TemporaryDirectory(prefix="qc-persistent-browser-http-")))
        self.root = self.host / "data"
        self.work = self.root / "qc_tool_work" / "work"
        self.incoming = self.root / "qc_tool_incoming" / "incoming"
        self.boundaries = self.root / "qc_tool_boundary" / "boundaries"
        self.published = self.root / "qc_tool_submission" / "submission"
        self.uploads = self.work / "product_definitions"
        self.installation = self.host / "installation" / "product_definitions"
        self.private = self.host / "private"
        for directory in (self.work, self.incoming, self.boundaries, self.published,
                          self.uploads, self.installation, self.private / "postgresql",
                          self.private / "frontend"):
            directory.mkdir(parents=True, exist_ok=True)
        self.marker = self.root / ".qc-tool-storage-id"
        self.identity = "eea-http-test-storage"
        self.marker.write_text(self.identity + "\n", encoding="utf-8")
        self.marker.chmod(0o600)
        self.enterContext(override_settings(
            MAINTENANCE_MODE=False, MEDIA_ROOT=str(self.incoming), QC_TOOL_STORAGE_ROOTS=[],
            QC_TOOL_PERSISTENT_STORAGE_ROOT=self.root,
            QC_TOOL_PERSISTENT_STORAGE_ID=self.identity,
            QC_TOOL_MAINTENANCE_DIR=self.work / "maintenance",
            QC_TOOL_TRANSFER_DIR=self.work / "data-transfer",
            FILE_UPLOAD_TEMP_DIR=str(self.work / "upload-staging"),
            S3_CREDENTIALS_DIR=self.work / "s3_credentials",
        ))
        self.enterContext(patch.dict(CONFIG, work_dir=self.work, incoming_dir=self.incoming,
                                    boundary_dir=self.boundaries, submission_dir=self.published,
                                    product_dirs=[self.installation]))
        administrator = get_user_model().objects.create_superuser(
            username="persistent-storage-administrator", email="persistent-storage@example.test",
            password="sufficient-test-password",
        )
        self.client.force_login(administrator)
        maintenance.read_status()

    @staticmethod
    def query(url):
        return parse_qs(urlsplit(url).query)

    def browse(self, path="", *, area="persistent"):
        return self.client.get(reverse("admin_storage"),
                               {"tab": "files", "area": area, "path": path})

    def original_version(self):
        payload = b'{\n  "description": "Stored original bytes",\n  "steps": []\n}\n'
        digest = sha256(payload).hexdigest()
        original = self.uploads / ".versions" / "example" / (digest + ".json")
        original.parent.mkdir(parents=True)
        original.write_bytes(payload)
        return original, payload

    def test_storage_lands_on_persistent_files_and_explicit_libraries_remain_available(self):
        response = self.client.get(reverse("admin_storage"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.query(response["Location"]), {"tab": ["files"], "area": ["persistent"]})
        opened = self.client.get(response["Location"])
        self.assertContains(opened, "<h1>Persistent storage</h1>", html=True)
        library = self.client.get(reverse("admin_storage"), {"tab": "deliveries"})
        self.assertEqual(library.status_code, 200)
        self.assertEqual(library.context["storage_tab"], "deliveries")

    def test_persistent_location_is_primary_and_nested_readonly_trees_are_not_duplicated(self):
        response = self.client.get(reverse("admin_storage"), {"tab": "files"})
        self.assertEqual(response.status_code, 200)
        locations = response.context["storage_locations"]
        self.assertEqual(locations[0]["key"], "persistent")
        persistent = locations[0]
        self.assertEqual(persistent["label"], "Persistent storage")
        self.assertEqual(persistent["storage_path"], str(self.root))
        self.assertTrue(persistent["available"])
        self.assertTrue(persistent["read_only"])
        self.assertFalse(persistent["can_trash"])
        self.assertEqual(self.query(persistent["url"]), {"tab": ["files"], "area": ["persistent"]})
        keys = {row["key"] for row in locations}
        self.assertFalse(keys & {"work", "jobs", "boundaries", "published", "uploaded-specifications"})
        # The upload shortcut keeps its existing narrowly scoped Trash policy.
        incoming = next(row for row in locations if row["key"] == "incoming")
        self.assertFalse(incoming["read_only"])
        self.assertTrue(incoming["can_trash"])
        installation = response.context["storage_installation_locations"]
        self.assertEqual([row["key"] for row in installation], ["spec-0"])
        self.assertEqual(installation[0]["storage_path"], str(self.installation))

    def test_walk_real_persistent_folders_and_saved_versions_without_rewriting_originals(self):
        original, payload = self.original_version()
        current = ""
        for name in ("qc_tool_work", "work", "product_definitions", ".versions", "example"):
            response = self.browse(current)
            self.assertEqual(response.status_code, 200)
            row = next(row for row in response.context["listing"]["entries"] if row["name"] == name)
            self.assertEqual(row["kind"], "directory")
            self.assertEqual(self.query(row["url"])["area"], ["persistent"])
            response = self.client.get(row["url"])
            self.assertEqual(response.status_code, 200)
            current = row["path"]
        self.assertEqual(response.context["storage_path"], str(original.parent))
        self.assertEqual([crumb["label"] for crumb in response.context["crumbs"]][-5:],
                         ["qc_tool_work", "work", "product_definitions", ".versions", "example"])
        entry = response.context["listing"]["entries"][0]
        self.assertEqual(entry["name"], original.name)
        detail = self.client.get(entry["url"])
        self.assertEqual(detail.status_code, 200)
        self.assertFalse(detail.context["review"]["can_quarantine"])
        self.assertEqual(self.query(detail.context["parent_url"])["path"], [current])
        download = self.client.get(detail.context["download_url"])
        self.assertEqual(download.status_code, 200)
        self.assertEqual(b"".join(download.streaming_content), payload)
        self.assertEqual(original.read_bytes(), payload)

    def test_other_persistent_folders_and_zip_download_use_actual_relative_paths(self):
        folder = self.root / "datasets" / "October"
        folder.mkdir(parents=True)
        payload = b"operator-owned persistent file\n"
        original = folder / "read me.txt"
        original.write_bytes(payload)
        opened = self.browse("datasets/October")
        self.assertEqual(opened.status_code, 200)
        self.assertEqual(opened.context["storage_path"], str(folder))
        row = opened.context["listing"]["entries"][0]
        self.assertEqual(row["name"], "read me.txt")
        archive = self.client.get(reverse("admin_storage_archive"),
                                  {"area": "persistent", "path": "datasets"})
        self.assertEqual(archive.status_code, 200)
        with ZipFile(BytesIO(b"".join(archive.streaming_content))) as package:
            self.assertEqual(package.read("files/datasets/October/read me.txt"), payload)
            self.assertIsNone(package.testzip())
        self.assertEqual(original.read_bytes(), payload)

    def test_root_zip_preserves_version_bytes_and_excludes_private_application_files(self):
        original, payload = self.original_version()
        self.write_private_files()
        response = self.client.get(reverse("admin_storage_archive"), {"area": "persistent"})
        self.assertEqual(response.status_code, 200)
        zipped = b"".join(response.streaming_content)
        with ZipFile(BytesIO(zipped)) as package:
            self.assertEqual(package.read("files/" + original.relative_to(self.root).as_posix()), payload)
            self.assertFalse(any("worker.token" in name or "s3_credentials" in name
                                 or "upload-staging" in name or "/.state/" in name
                                 or ".qc-tool-storage-id" in name for name in package.namelist()))
            for name in package.namelist():
                if not name.endswith("/"):
                    self.assertNotIn(b"private sentinel payload", package.read(name))

    def write_private_files(self):
        relative_paths = (
            "qc_tool_work/work/worker.token",
            "qc_tool_work/work/s3_credentials/example.json",
            "qc_tool_work/work/upload-staging/upload.tmp",
            "qc_tool_work/work/maintenance/private.json",
            "qc_tool_work/work/data-transfer/private.json",
            "qc_tool_work/work/product_definitions/.state/example.json",
            "qc_tool_work/work/product_definitions/.upload.lock",
            "qc_tool_boundary/boundaries/.boundary-current",
            "qc_tool_boundary/boundaries/.boundary-package.lock",
        )
        for relative in relative_paths:
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"private sentinel payload")
        return relative_paths

    def test_private_storage_cannot_be_reached_through_persistent_parent_or_legacy_alias(self):
        protected = self.write_private_files()
        listed = self.browse("qc_tool_work/work")
        self.assertEqual(listed.status_code, 200)
        names = {row["name"] for row in listed.context["listing"]["entries"]}
        self.assertFalse(names & {"worker.token", "s3_credentials", "upload-staging", "maintenance", "data-transfer"})
        for relative in (*protected, ".qc-tool-storage-id"):
            for route in ("admin_storage_file", "admin_storage_download"):
                with self.subTest(path=relative, route=route):
                    response = self.client.get(reverse(route), {"area": "persistent", "path": relative})
                    self.assertIn(response.status_code, (400, 404, 409))
                    self.assertNotContains(response, "private sentinel payload", status_code=response.status_code)
        for path in ("worker.token", "s3_credentials/example.json", "upload-staging/upload.tmp"):
            response = self.client.get(reverse("admin_storage_download"), {"area": "work", "path": path})
            self.assertIn(response.status_code, (400, 404, 409))

    def test_postgresql_and_frontend_private_siblings_are_outside_the_browser(self):
        secret = self.private / "postgresql" / "PG_VERSION"
        secret.write_bytes(b"private postgres sentinel")
        (self.private / "frontend" / "private.json").write_bytes(b"private frontend sentinel")
        (self.root / "private-link").symlink_to(self.private, target_is_directory=True)
        listed = self.browse()
        self.assertEqual(listed.status_code, 200)
        names = {row["name"] for row in listed.context["listing"]["entries"]}
        self.assertNotIn("private", names)
        self.assertNotIn("private-link", names)
        for path in ("../private/postgresql/PG_VERSION", "private-link/postgresql/PG_VERSION",
                     str(secret), "../private/frontend/private.json"):
            for route in ("admin_storage_file", "admin_storage_download"):
                with self.subTest(path=path, route=route):
                    response = self.client.get(reverse(route), {"area": "persistent", "path": path})
                    self.assertIn(response.status_code, (400, 404, 409))
                    self.assertNotContains(response, "private postgres sentinel", status_code=response.status_code)
                    self.assertNotContains(response, "private frontend sentinel", status_code=response.status_code)

    def test_persistent_alias_is_readonly_and_incoming_shortcut_keeps_narrow_trash_policy(self):
        upload = self.incoming / "uploader" / "orphan.zip"
        upload.parent.mkdir()
        upload.write_bytes(b"original upload")
        readonly = self.client.get(reverse("admin_storage_file"),
                                   {"area": "persistent", "path": "qc_tool_incoming/incoming/uploader/orphan.zip"})
        managed = self.client.get(reverse("admin_storage_file"),
                                  {"area": "incoming", "path": "uploader/orphan.zip"})
        self.assertEqual(readonly.status_code, 200)
        self.assertEqual(managed.status_code, 200)
        self.assertFalse(readonly.context["review"]["can_quarantine"])
        self.assertTrue(managed.context["review"]["can_quarantine"])
        self.assertEqual(upload.read_bytes(), b"original upload")

    def test_invalid_storage_identity_fails_closed_even_through_preexisting_area_links(self):
        original = self.work / "result.txt"
        original.write_bytes(b"retained result")
        outside_marker = self.host / "outside-marker"
        outside_marker.write_text(self.identity + "\n", encoding="utf-8")
        for variant in ("missing", "wrong", "symlink"):
            with self.subTest(marker=variant):
                self.marker.unlink(missing_ok=True)
                if variant == "wrong":
                    self.marker.write_text("different-storage\n", encoding="utf-8")
                    self.marker.chmod(0o600)
                elif variant == "symlink":
                    self.marker.symlink_to(outside_marker)
                try:
                    for area, path in (("persistent", "qc_tool_work/work/result.txt"),
                                       ("work", "result.txt")):
                        response = self.browse(area=area)
                        self.assertEqual(response.status_code, 503)
                        self.assertTrue(response.context["storage_error"])
                        for route in ("admin_storage_file", "admin_storage_download"):
                            response = self.client.get(reverse(route), {"area": area, "path": path})
                            self.assertEqual(response.status_code, 503)
                            self.assertNotContains(response, "retained result", status_code=503)
                    self.assertEqual(original.read_bytes(), b"retained result")
                    if variant == "missing":
                        self.assertFalse(self.marker.exists())
                finally:
                    self.marker.unlink(missing_ok=True)
                    self.marker.write_text(self.identity + "\n", encoding="utf-8")
                    self.marker.chmod(0o600)

    def test_missing_mount_is_visible_as_unavailable_without_creating_it(self):
        absent = self.host / "not-mounted"
        with override_settings(QC_TOOL_PERSISTENT_STORAGE_ROOT=absent):
            response = self.client.get(reverse("admin_storage"), {"tab": "files"})
            self.assertEqual(response.status_code, 200)
            location = next(row for row in response.context["storage_locations"] if row["key"] == "persistent")
            self.assertFalse(location["available"])
            self.assertTrue(location["message"])
            opened = self.browse()
            self.assertEqual(opened.status_code, 503)
            self.assertFalse(absent.exists())
