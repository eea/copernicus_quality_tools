"""Boundary upload HTTP policy and failures preserve active boundary files."""

import errno
from html.parser import HTMLParser
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import PropertyMock, patch
from zipfile import ZipFile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.uploadhandler import FileUploadHandler
from django.db import connection
from django.template.defaultfilters import filesizeformat
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from qc_tool.common import CONFIG
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.dashboard.services import maintenance
from qc_tool.frontend.dashboard.services.boundaries import (
    replace_boundary_package,
    resolve_boundary_generation,
)
from qc_tool.frontend.dashboard.views import boundaries as boundary_views


MiB = 1024**2


def _archive(raster=b"new-raster", vector=b"new-vector"):
    stream = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("raster/new.tif", raster)
        archive.writestr("vector/new.gpkg", vector)
    return stream.getvalue()


class _UploadForm(HTMLParser):
    def __init__(self, response):
        super().__init__()
        self.attributes = None
        self.file_disabled = None
        self.fieldsets = []
        self.feed(response.content.decode(response.charset))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form" and attrs.get("id") == "boundary-upload-form":
            self.attributes = attrs
        if tag == "fieldset":
            self.fieldsets.append("disabled" in attrs)
        if tag == "input" and attrs.get("type") == "file":
            self.file_disabled = "disabled" in attrs or any(self.fieldsets)

    def handle_endtag(self, tag):
        if tag == "fieldset":
            self.fieldsets.pop()


class NoSpaceUploadHandler(FileUploadHandler):
    """Exercise a real multipart-storage failure, including CSRF middleware."""

    def receive_data_chunk(self, raw_data, start):
        raise OSError(errno.ENOSPC, "/private/secret-spool")

    def file_complete(self, file_size):
        return None


@override_settings(MAINTENANCE_MODE=False)
class BoundaryUploadHttpTests(TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory(prefix="qc-boundary-http-"))).resolve()
        self.root = self.directory / "boundaries"
        self.upload_temporary = self.directory / "upload-temporary"
        self.upload_temporary.mkdir()
        self.enterContext(override_settings(
            QC_TOOL_MAINTENANCE_DIR=self.directory / "maintenance",
            QC_TOOL_TRANSFER_DIR=self.directory / "transfers",
            FILE_UPLOAD_TEMP_DIR=str(self.upload_temporary),
            QC_TOOL_BOUNDARY_PACKAGE_LIMITS={},
        ))
        self.enterContext(patch.dict(CONFIG, {"boundary_dir": self.root}))
        self.active = replace_boundary_package(io.BytesIO(_archive()), self.root)
        self.user = get_user_model().objects.create_user(username="boundary-http-editor")
        self.user.groups.add(Group.objects.get(name=Role.ADMIN.value))
        self.client.force_login(self.user)
        # Initialize only the isolated fixture's admission files before checking
        # that opening the upload page cannot create/update application state.
        with maintenance.application_activity():
            pass
        self.page_url = reverse("boundaries_upload")
        self.upload_url = reverse("boundaries_upload_data")

    def upload(self, content=None):
        content = _archive() if content is None else content
        return self.client.post(self.upload_url, {
            "file": SimpleUploadedFile("boundaries.zip", content, content_type="application/zip"),
        })

    def assert_active_unchanged(self):
        generation = resolve_boundary_generation(self.root)
        self.assertEqual(generation.generation_id, self.active.generation_id)
        self.assertEqual((generation.raster_dir / "new.tif").read_bytes(), b"new-raster")
        self.assertEqual((generation.vector_dir / "new.gpkg").read_bytes(), b"new-vector")
        self.assertEqual(list(self.root.glob(".boundary-staging-*")), [])

    def snapshot(self):
        result = {}
        for path in (self.directory, *self.directory.rglob("*")):
            status = path.lstat()
            content = str(path.readlink()) if path.is_symlink() else path.read_bytes() if path.is_file() else None
            result[str(path.relative_to(self.directory))] = (status.st_mode, status.st_mtime_ns, content)
        return result

    def test_get_displays_configured_limits_capacity_and_does_not_write(self):
        configured = {"max_archive_bytes": 8192, "max_member_bytes": 1024, "max_uncompressed_bytes": 4096}
        before = self.snapshot()

        def disk_usage(path):
            free = 768 * MiB if Path(path) == self.upload_temporary else 1024 * MiB
            return SimpleNamespace(free=free, total=2048 * MiB, used=2048 * MiB - free)

        with override_settings(QC_TOOL_BOUNDARY_PACKAGE_LIMITS=configured):
            with patch.object(boundary_views.shutil, "disk_usage", side_effect=disk_usage):
                with CaptureQueriesContext(connection) as queries:
                    response = self.client.get(self.page_url)

        self.assertEqual(response.status_code, 200)
        limits = response.context["boundary_upload_limits"]
        self.assertEqual((limits.max_archive_bytes, limits.max_member_bytes, limits.max_uncompressed_bytes),
                         (8192, 1024, 4096))
        self.assertEqual(response.context["boundary_storage_free"], 1024 * MiB)
        self.assertEqual(response.context["boundary_available_upload_bytes"], 512 * MiB)
        form = _UploadForm(response)
        self.assertEqual(form.attributes["data-max-archive-bytes"], "8192")
        self.assertEqual(form.attributes["data-available-upload-bytes"], str(512 * MiB))
        self.assertFalse(form.file_disabled)
        for maximum in configured.values():
            self.assertContains(response, filesizeformat(maximum))
        self.assertEqual(self.snapshot(), before)
        mutations = [query["sql"] for query in queries
                     if query["sql"].lstrip().split()[0].upper() in
                     {"INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP"}]
        self.assertEqual(mutations, [])

    def test_get_capacity_uses_smaller_boundary_filesystem_and_clamps_headroom_at_zero(self):
        for boundary_free, temporary_free, expected in (
            (768 * MiB, 1024 * MiB, 512 * MiB),
            (128 * MiB, 1024 * MiB, 0),
            (1024 * MiB, 128 * MiB, 0),
            (1024 * MiB, 0, 0),
        ):
            with self.subTest(boundary_free=boundary_free, temporary_free=temporary_free):
                def disk_usage(path):
                    free = temporary_free if Path(path) == self.upload_temporary else boundary_free
                    return SimpleNamespace(free=free, total=2048 * MiB, used=2048 * MiB - free)

                with patch.object(boundary_views.shutil, "disk_usage", side_effect=disk_usage):
                    response = self.client.get(self.page_url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["boundary_available_upload_bytes"], expected)
                self.assertEqual(_UploadForm(response).attributes["data-available-upload-bytes"], str(expected))

    def test_get_capacity_does_not_create_a_fresh_boundary_root(self):
        missing = self.directory / "not-created" / "boundaries"
        before = self.snapshot()
        with patch.dict(CONFIG, {"boundary_dir": missing}):
            response = self.client.get(self.page_url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("boundary_storage_free", response.context)
        self.assertFalse(missing.parent.exists())
        self.assertEqual(self.snapshot(), before)

    def test_catalog_obeys_the_same_configured_entry_bound_as_package_uploads(self):
        generation = resolve_boundary_generation(self.root)
        (generation.raster_dir / "another.tif").write_bytes(b"another-raster")
        url = reverse("boundaries_json", args=["raster"])
        with override_settings(QC_TOOL_BOUNDARY_PACKAGE_LIMITS={"max_members": 1}):
            rejected = self.client.get(url)
        self.assertEqual(rejected.status_code, 413)
        self.assertEqual(rejected.json()["code"], "boundary_catalog_limit_exceeded")
        with override_settings(QC_TOOL_BOUNDARY_PACKAGE_LIMITS={"max_members": 20_000}):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual({item["filename"] for item in response.json()}, {"another.tif", "new.tif"})
        self.assert_active_unchanged()

    @override_settings(QC_TOOL_BOUNDARY_PACKAGE_LIMITS={"max_archive_bytes": "invalid"})
    def test_invalid_configuration_disables_page_and_rejects_upload_before_storage_work(self):
        before = self.snapshot()
        with patch.object(boundary_views, "replace_boundary_package") as replace:
            page = self.client.get(self.page_url)
            response = self.upload()

        self.assertEqual(page.status_code, 200)
        self.assertTrue(_UploadForm(page).file_disabled)
        self.assertNotIn("boundary_upload_limits", page.context)
        self.assertContains(page, "storage or safety limits are not configured safely")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["code"], "boundary_package_configuration_error")
        self.assertNotIn("invalid", response.json()["message"])
        replace.assert_not_called()
        self.assert_active_unchanged()
        self.assertEqual(self.snapshot(), before)

    def test_unavailable_upload_temporary_storage_disables_page_without_private_diagnostics(self):
        original = boundary_views.shutil.disk_usage

        def disk_usage(path):
            if Path(path) == self.upload_temporary:
                raise OSError(errno.EACCES, "/private/secret-spool")
            return original(path)

        with patch.object(boundary_views.shutil, "disk_usage", side_effect=disk_usage):
            response = self.client.get(self.page_url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(_UploadForm(response).file_disabled)
        self.assertContains(response, "Temporary upload storage is unavailable")
        self.assertNotContains(response, "/private/secret-spool")
        self.assert_active_unchanged()

    @override_settings(QC_TOOL_BOUNDARY_PACKAGE_LIMITS={"max_archive_bytes": 8})
    def test_configured_archive_limit_is_applied_by_real_upload_service(self):
        response = self.upload()

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["code"], "boundary_package_limit_exceeded")
        self.assertIn("8 bytes", response.json()["message"])
        self.assert_active_unchanged()

    @override_settings(QC_TOOL_BOUNDARY_PACKAGE_LIMITS={"max_member_bytes": 8})
    def test_configured_expanded_member_limit_propagates_safe_actionable_413(self):
        response = self.upload(_archive(raster=b"123456789", vector=b"ok"))

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["code"], "boundary_package_limit_exceeded")
        self.assertIn("9 bytes", response.json()["message"])
        self.assertIn("8 bytes", response.json()["message"])
        self.assertNotIn("new.tif", response.json()["message"])
        self.assertEqual(set(response.json()), {"is_valid", "code", "message"})
        self.assertFalse(response.json()["is_valid"])
        self.assert_active_unchanged()

    def test_real_capacity_failure_propagates_507_and_preserves_active_package(self):
        with patch.object(boundary_views.shutil, "disk_usage", return_value=SimpleNamespace(
            free=0, total=1024 * MiB, used=1024 * MiB,
        )):
            response = self.upload()

        self.assertEqual(response.status_code, 507)
        self.assertEqual(response.json()["code"], "boundary_package_insufficient_space")
        self.assertIn("current package remains active", response.json()["message"])
        self.assertNotIn(str(self.root), response.json()["message"])
        self.assert_active_unchanged()

    @override_settings(QC_TOOL_BOUNDARY_PACKAGE_LIMITS={"max_member_bytes": 16, "max_uncompressed_bytes": 32})
    def test_valid_configured_package_returns_activated_generation(self):
        response = self.upload(_archive(raster=b"replacement", vector=b"ok"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["is_valid"])
        self.assertEqual(payload["package"]["file_count"], 2)
        self.assertEqual(payload["package"]["uncompressed_size"], len(b"replacementok"))
        generation = resolve_boundary_generation(self.root)
        self.assertEqual(payload["package"]["generation_id"], generation.generation_id)
        self.assertNotEqual(generation.generation_id, self.active.generation_id)
        self.assertEqual((generation.raster_dir / "new.tif").read_bytes(), b"replacement")

    def test_default_user_cannot_open_or_submit_package_replacement(self):
        viewer = get_user_model().objects.create_user(username="boundary-http-viewer")
        self.client.force_login(viewer)
        with patch.object(boundary_views, "replace_boundary_package") as replace:
            page = self.client.get(self.page_url)
            response = self.upload()

        self.assertEqual(page.status_code, 403)
        self.assertEqual(response.status_code, 403)
        replace.assert_not_called()
        self.assert_active_unchanged()

    def test_multipart_disk_full_before_view_with_real_csrf_checks_returns_safe_507(self):
        client = Client(enforce_csrf_checks=True, raise_request_exception=False)
        client.force_login(self.user)
        page = client.get(self.page_url)
        self.assertEqual(page.status_code, 200)
        token = client.cookies["csrftoken"].value
        with override_settings(FILE_UPLOAD_HANDLERS=[f"{__name__}.NoSpaceUploadHandler"]):
            with patch.object(boundary_views, "replace_boundary_package") as replace:
                response = client.post(self.upload_url, {
                    "file": SimpleUploadedFile("boundaries.zip", _archive(), content_type="application/zip"),
                }, HTTP_X_CSRFTOKEN=token)

        self.assertEqual(response.status_code, 507)
        self.assertEqual(response.json()["code"], "boundary_upload_insufficient_space")
        self.assertNotIn("/private", response.json()["message"])
        replace.assert_not_called()
        self.assert_active_unchanged()

    def test_administrator_upload_without_csrf_is_rejected_before_service(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        with patch.object(boundary_views, "replace_boundary_package") as replace:
            response = client.post(self.upload_url, {
                "file": SimpleUploadedFile("boundaries.zip", _archive(), content_type="application/zip"),
            })

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "csrf_failed")
        replace.assert_not_called()
        self.assert_active_unchanged()


class BoundaryUploadReceptionFailureTests(SimpleTestCase):
    def test_disk_full_or_quota_error_during_multipart_parsing_returns_safe_507(self):
        for error_number in (errno.ENOSPC, errno.EDQUOT):
            with self.subTest(error_number=error_number):
                request = RequestFactory().post(reverse("boundaries_upload_data"), {})
                with patch.object(type(request), "FILES", new_callable=PropertyMock,
                                  side_effect=OSError(error_number, "/private/secret-spool")):
                    with patch.object(boundary_views, "replace_boundary_package") as replace:
                        response = boundary_views.boundaries_upload(request)

                self.assertEqual(response.status_code, 507)
                self.assertIn(b"boundary_upload_insufficient_space", response.content)
                self.assertIn(b"No boundary package was activated", response.content)
                self.assertNotIn(b"/private", response.content)
                replace.assert_not_called()

    def test_other_multipart_storage_error_returns_safe_unavailable_response(self):
        request = RequestFactory().post(reverse("boundaries_upload_data"), {})
        with patch.object(type(request), "FILES", new_callable=PropertyMock,
                          side_effect=OSError(errno.EIO, "/private/secret-spool")):
            with patch.object(boundary_views, "replace_boundary_package") as replace:
                response = boundary_views.boundaries_upload(request)

        self.assertEqual(response.status_code, 503)
        self.assertIn(b"boundary_upload_unavailable", response.content)
        self.assertNotIn(b"/private", response.content)
        replace.assert_not_called()
