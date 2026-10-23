"""Boundary package size/capacity failures preserve the active generation."""

import errno
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from qc_tool.frontend.dashboard.services.boundaries import (
    BoundaryPackageConfigurationError,
    BoundaryPackageInsufficientSpace,
    BoundaryPackageLimitExceeded,
    BoundaryPackageLimits,
    BoundaryPackagePromotionError,
    inspect_boundary_capacity,
    replace_boundary_package,
    resolve_boundary_generation,
)
from qc_tool.frontend.dashboard.services.boundaries import service
from qc_tool.frontend.dashboard.services.boundaries.archive import validate_archive
from qc_tool.frontend.dashboard.services.boundaries.archive.copying import copy_archive_bounded
from qc_tool.frontend.dashboard.services.boundaries.layout import CURRENT_POINTER_NAME, GENERATIONS_DIRECTORY_NAME


def _archive():
    stream = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("raster/new.tif", b"new-raster")
        archive.writestr("vector/new.gpkg", b"new-vector")
    stream.seek(0)
    return stream


class DeclaredUpload(io.BytesIO):
    def __init__(self, content, size):
        super().__init__(content)
        self.size = size


class BoundaryCapacityTests(TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix="qc-boundary-capacity-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve() / "boundaries"
        for name in ("raster", "vector"):
            directory = self.root / name
            directory.mkdir(parents=True)
            (directory / "old.dat").write_bytes(b"old-boundary")

    def assert_originals_unchanged(self):
        for name in ("raster", "vector"):
            self.assertFalse((self.root / name).is_symlink())
            self.assertEqual((self.root / name / "old.dat").read_bytes(), b"old-boundary")
        self.assertFalse((self.root / CURRENT_POINTER_NAME).exists())
        self.assertFalse((self.root / GENERATIONS_DIRECTORY_NAME).exists())
        self.assertEqual(list(self.root.glob(".boundary-staging-*")), [])

    def test_declared_oversized_upload_is_rejected_before_root_or_staging_copy(self):
        limits = BoundaryPackageLimits(max_archive_bytes=1024)
        upload = DeclaredUpload(b"not read", 2048)
        missing = Path(self.temporary.name) / "never-created"
        with patch.object(service, "copy_archive_bounded") as copy:
            with self.assertRaises(BoundaryPackageLimitExceeded) as raised:
                replace_boundary_package(upload, missing, limits=limits)
        copy.assert_not_called()
        self.assertFalse(missing.exists())
        self.assertEqual(upload.tell(), 0)
        self.assertEqual((raised.exception.actual, raised.exception.maximum), (2048, 1024))
        self.assertIn("2.00 KiB", str(raised.exception))
        self.assertIn("1.00 KiB", str(raised.exception))

    def test_local_archive_size_is_rejected_without_a_staging_copy(self):
        source = Path(self.temporary.name) / "source.zip"
        source.write_bytes(b"0123456789")
        with patch.object(service, "copy_archive_bounded") as copy:
            with self.assertRaises(BoundaryPackageLimitExceeded):
                replace_boundary_package(source, self.root, limits=BoundaryPackageLimits(max_archive_bytes=8))
        copy.assert_not_called()
        self.assertEqual(source.read_bytes(), b"0123456789")
        self.assert_originals_unchanged()

    def test_understated_upload_size_cannot_bypass_the_streaming_bound(self):
        source = DeclaredUpload(b"0123456789", 0)
        destination = Path(self.temporary.name) / "staging.zip"
        with self.assertRaises(BoundaryPackageLimitExceeded) as raised:
            copy_archive_bounded(source, destination, 8)
        self.assertEqual(raised.exception.limit, "archive_bytes")
        self.assertEqual((raised.exception.actual, raised.exception.maximum), (10, 8))
        self.assertLessEqual(destination.stat().st_size, 8)
        self.assertEqual(source.tell(), 0)

    def test_known_archive_cannot_start_a_copy_without_sufficient_space(self):
        stream = _archive()
        upload = DeclaredUpload(stream.getvalue(), len(stream.getvalue()))
        with patch.object(service, "inspect_boundary_capacity", return_value={"free_bytes": 0}):
            with patch.object(service, "copy_archive_bounded") as copy:
                with self.assertRaises(BoundaryPackageInsufficientSpace) as raised:
                    replace_boundary_package(upload, self.root)
        copy.assert_not_called()
        self.assertEqual(raised.exception.status_code, 507)
        self.assertIn("current package remains active", str(raised.exception))
        self.assert_originals_unchanged()

    def test_expansion_capacity_is_checked_on_staging_filesystem_before_extraction(self):
        inspected = []
        def capacity(path):
            inspected.append(Path(path))
            return {"free_bytes": 0}
        with patch.object(service, "inspect_boundary_capacity", side_effect=capacity):
            with patch.object(service, "extract_archive") as extract:
                with self.assertRaises(BoundaryPackageInsufficientSpace) as raised:
                    replace_boundary_package(_archive(), self.root)
        extract.assert_not_called()
        self.assertEqual(len(inspected), 1)
        self.assertEqual(inspected[0].parent, self.root)
        self.assertTrue(inspected[0].name.startswith(".boundary-staging-"))
        # A first activation retains a duplicate of both legacy files.
        expected_payload = len(b"new-rasternew-vector") + 2 * len(b"old-boundary")
        self.assertEqual(raised.exception.required_bytes, expected_payload + 256 * 1024**2)
        self.assert_originals_unchanged()

    def test_legacy_snapshot_space_is_not_mistaken_for_already_allocated_capacity(self):
        expanded = len(b"new-rasternew-vector")
        without_legacy = expanded + 256 * 1024**2
        with patch.object(service, "inspect_boundary_capacity", return_value={"free_bytes": without_legacy}):
            with self.assertRaises(BoundaryPackageInsufficientSpace):
                replace_boundary_package(_archive(), self.root)
        self.assert_originals_unchanged()

    def test_existing_managed_generation_and_current_pointer_survive_capacity_failure(self):
        first = replace_boundary_package(_archive(), self.root)
        pointer = (self.root / CURRENT_POINTER_NAME).readlink()
        generations = set((self.root / GENERATIONS_DIRECTORY_NAME).iterdir())
        with patch.object(service, "inspect_boundary_capacity", return_value={"free_bytes": 0}):
            with self.assertRaises(BoundaryPackageInsufficientSpace):
                replace_boundary_package(_archive(), self.root)
        self.assertEqual(resolve_boundary_generation(self.root).generation_id, first.generation_id)
        self.assertEqual((self.root / CURRENT_POINTER_NAME).readlink(), pointer)
        self.assertEqual(set((self.root / GENERATIONS_DIRECTORY_NAME).iterdir()), generations)
        self.assertEqual(list(self.root.glob(".boundary-staging-*")), [])

    def test_post_pointer_fsync_failure_does_not_claim_the_old_package_remains_active(self):
        first = replace_boundary_package(_archive(), self.root)
        stream = io.BytesIO()
        with ZipFile(stream, "w") as archive:
            archive.writestr("raster/second.tif", b"second-generation")
        stream.seek(0)
        with patch("qc_tool.frontend.dashboard.services.boundaries.storage.activation.fsync_directory",
                   side_effect=OSError(errno.EIO, "/private/fsync detail")):
            with self.assertRaises(BoundaryPackagePromotionError) as raised:
                replace_boundary_package(stream, self.root)
        current = resolve_boundary_generation(self.root)
        self.assertNotEqual(current.generation_id, first.generation_id)
        self.assertEqual((current.raster_dir / "second.tif").read_bytes(), b"second-generation")
        self.assertIn("activation could not be confirmed", str(raised.exception))
        self.assertNotIn("previous package remains active", str(raised.exception))
        self.assertNotIn("/private", str(raised.exception))

    def test_space_error_after_activation_is_uncertain_promotion_not_pre_activation_507(self):
        replace_boundary_package(_archive(), self.root)
        for error_number in (errno.ENOSPC, errno.EDQUOT):
            with self.subTest(errno=error_number):
                before = resolve_boundary_generation(self.root).generation_id
                with patch.object(service, "remove_tree", side_effect=OSError(error_number, "/private/cleanup detail")):
                    with self.assertRaises(BoundaryPackagePromotionError) as raised:
                        replace_boundary_package(_archive(), self.root)
                self.assertEqual(raised.exception.status_code, 500)
                self.assertNotIsInstance(raised.exception, BoundaryPackageInsufficientSpace)
                self.assertIn("activation could not be confirmed", str(raised.exception))
                self.assertNotIn("remains active", str(raised.exception))
                self.assertNotIn("No boundary package was activated", str(raised.exception))
                self.assertNotIn("/private", str(raised.exception))
                self.assertNotEqual(resolve_boundary_generation(self.root).generation_id, before)

    def test_capacity_inspection_is_read_only_and_does_not_create_missing_roots(self):
        before = set(self.root.rglob("*"))
        capacity = inspect_boundary_capacity(self.root)
        self.assertEqual(set(capacity), {"free_bytes", "total_bytes", "used_bytes"})
        self.assertTrue(all(type(value) is int and value >= 0 for value in capacity.values()))
        self.assertEqual(set(self.root.rglob("*")), before)
        missing = self.root / "missing"
        self.assertGreaterEqual(inspect_boundary_capacity(missing)["free_bytes"], 0)
        self.assertFalse(missing.exists())
        link = Path(self.temporary.name) / "linked-root"
        link.symlink_to(self.root)
        with self.assertRaises(BoundaryPackageConfigurationError):
            inspect_boundary_capacity(link)

    def test_fresh_nested_root_uses_real_ancestor_and_rejects_files_or_links(self):
        missing = self.root / "fresh" / "nested"
        with patch.object(service.shutil, "disk_usage", wraps=service.shutil.disk_usage) as usage:
            inspect_boundary_capacity(missing)
        usage.assert_called_once_with(self.root)
        self.assertFalse(missing.parent.exists())
        file_path = self.root / "not-a-directory"
        file_path.write_bytes(b"keep")
        link = self.root / "linked-parent"
        link.symlink_to(self.root, target_is_directory=True)
        for root in (file_path, file_path / "missing", link / "missing", Path("relative/root"), Path("/"), None):
            with self.subTest(root=root), self.assertRaises(BoundaryPackageConfigurationError):
                inspect_boundary_capacity(root)

    def test_unavailable_capacity_is_safe_and_never_starts_extraction(self):
        with patch.object(service.shutil, "disk_usage", side_effect=OSError("/private/secret storage detail")):
            with patch.object(service, "extract_archive") as extract:
                with self.assertRaises(BoundaryPackageConfigurationError) as raised:
                    replace_boundary_package(_archive(), self.root)
        extract.assert_not_called()
        self.assertNotIn("/private", str(raised.exception))
        self.assert_originals_unchanged()

    def test_space_exhausted_after_preflight_is_typed_and_does_not_activate(self):
        with patch.object(service, "extract_archive", side_effect=OSError(errno.ENOSPC, "/private/disk detail")):
            with self.assertRaises(BoundaryPackageInsufficientSpace) as raised:
                replace_boundary_package(_archive(), self.root)
        self.assertEqual(raised.exception.status_code, 507)
        self.assertNotIn("/private", str(raised.exception))
        self.assert_originals_unchanged()

    def test_unsafe_or_unbounded_legacy_tree_is_refused_before_extraction(self):
        link = self.root / "raster" / "private-link"
        link.symlink_to(Path(self.temporary.name) / "outside")
        with patch.object(service, "extract_archive") as extract:
            with self.assertRaises(BoundaryPackageConfigurationError):
                replace_boundary_package(_archive(), self.root)
        extract.assert_not_called()
        link.unlink()
        with patch.object(service, "_MAX_CAPACITY_SCAN_ENTRIES", 1):
            with self.assertRaises(BoundaryPackageConfigurationError):
                replace_boundary_package(_archive(), self.root)
        self.assert_originals_unchanged()


class BoundaryLimitMessageTests(TestCase):
    def test_messages_show_measured_limits_without_diagnostic_paths(self):
        for limit, actual, maximum in (
            ("archive_bytes", 2048, 1024), ("member_bytes", 2048, 1024),
            ("uncompressed_bytes", 2048, 1024), ("members", 10, 9),
            ("path_bytes", 10, 9), ("component_bytes", 10, 9),
            ("path_depth", 10, 9), ("compression_ratio", 101.5, 100),
        ):
            with self.subTest(limit=limit):
                error = BoundaryPackageLimitExceeded("/private/archive/member-secret", limit=limit,
                                                      actual=actual, maximum=maximum)
                self.assertEqual(str(error), error.user_message)
                self.assertNotIn("/private", str(error))
                self.assertNotIn("member-secret", str(error))
                self.assertIn("configured limit", str(error))
                self.assertEqual((error.actual, error.maximum), (actual, maximum))
        error = BoundaryPackageLimitExceeded("/private/secret")
        self.assertNotIn("/private", str(error))

    def test_only_numeric_allowlisted_metadata_can_become_user_copy(self):
        for values in (
            {"limit": "/private/secret", "actual": 2, "maximum": 1},
            {"limit": "archive_bytes", "actual": "/private/secret", "maximum": 1},
            {"limit": "archive_bytes", "actual": 2, "maximum": True},
            {"limit": "archive_bytes", "actual": float("nan"), "maximum": 1},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                BoundaryPackageLimitExceeded(**values)

    def test_legitimate_large_manifest_passes_without_allocating_large_payloads(self):
        # Representative metadata from the real22GiB package: six large files,
        # 8,485 regular members and a total expansion of23,878,305,384 bytes.
        large = [545886208, 3515866983, 884103620, 2549752010, 3515866983, 1117678140]
        remainder = 23878305384 - sum(large)
        quotient, extra = divmod(remainder, 8485 - len(large))
        sizes = large + [quotient + (index < extra) for index in range(8485 - len(large))]
        entries = []
        for index, size in enumerate(sizes):
            entry = ZipInfo(f"raster/file-{index}.tif")
            entry.compress_type = ZIP_DEFLATED
            entry.file_size, entry.compress_size = size, max(1, size // 10)
            entries.append(entry)
        archive = Mock()
        archive.infolist.return_value = entries
        validated = validate_archive(archive, BoundaryPackageLimits())
        self.assertEqual((validated.file_count, validated.uncompressed_size), (8485, 23878305384))
        with self.assertRaises(BoundaryPackageLimitExceeded) as raised:
            validate_archive(archive, BoundaryPackageLimits(max_member_bytes=512 * 1024**2))
        self.assertEqual(raised.exception.limit, "member_bytes")
