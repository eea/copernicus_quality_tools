from __future__ import annotations

import io
import multiprocessing
import os
from pathlib import Path
import shutil
import stat
import struct
import tempfile
import time
from unittest import TestCase
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from qc_tool.frontend.dashboard.services.boundaries import (
    BoundaryPackageBusy,
    BoundaryGenerationUnavailable,
    BoundaryPackageConfigurationError,
    BoundaryPackageError,
    BoundaryPackageInternalError,
    BoundaryPackageInvalid,
    BoundaryPackageLimitExceeded,
    BoundaryPackageLimits,
    BoundaryPackagePromotionError,
    BoundaryPackageUnsafe,
    replace_boundary_package,
    resolve_boundary_generation,
)
from qc_tool.frontend.dashboard.services.boundaries.layout import (
    CURRENT_POINTER_NAME,
    GENERATIONS_DIRECTORY_NAME,
    LEGACY_BACKUPS_DIRECTORY_NAME,
)
from qc_tool.frontend.dashboard.services.boundaries.storage import boundary_package_lock


def _archive(entries, *, compression=ZIP_STORED):
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=compression) as zip_file:
        for name, value in entries:
            if isinstance(name, ZipInfo):
                zip_file.writestr(name, value)
            else:
                zip_file.writestr(name, value)
    buffer.seek(0)
    return buffer


def _hold_boundary_lock(root, ready, release):
    with boundary_package_lock(Path(root), timeout=2):
        ready.set()
        release.wait(5)


def _corrupt_first_member(archive):
    content = bytearray(archive.getvalue())
    with ZipFile(io.BytesIO(content), "r") as zip_file:
        info = zip_file.infolist()[0]
    filename_length, extra_length = struct.unpack_from(
        "<HH", content, info.header_offset + 26
    )
    data_offset = info.header_offset + 30 + filename_length + extra_length
    content[data_offset] ^= 0xFF
    return io.BytesIO(content)


class BoundaryPackageServiceTests(TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name) / "boundaries"
        self.root.mkdir()
        self._write_live_file("raster", "old.tif", b"old-raster")
        self._write_live_file("vector", "old.gpkg", b"old-vector")

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _write_live_file(self, directory, filename, content):
        target = self.root / directory / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    def _assert_old_package_is_active(self):
        self.assertEqual((self.root / "raster" / "old.tif").read_bytes(), b"old-raster")
        self.assertEqual((self.root / "vector" / "old.gpkg").read_bytes(), b"old-vector")
        self.assertFalse((self.root / "raster" / "new.tif").exists())
        self.assertFalse((self.root / "vector" / "new.gpkg").exists())

    def _assert_no_temporary_data(self):
        leftovers = [
            path.name
            for path in self.root.iterdir()
            if path.name.startswith((".boundary-staging-", ".boundary-backup-"))
        ]
        self.assertEqual(leftovers, [])

    def test_replaces_both_live_directories_and_discards_uploaded_zip(self):
        archive = _archive(
            [("raster/new.tif", b"new-raster"), ("vector/new.gpkg", b"new-vector")]
        )

        result = replace_boundary_package(archive, self.root)

        self.assertEqual((self.root / "raster" / "new.tif").read_bytes(), b"new-raster")
        self.assertEqual((self.root / "vector" / "new.gpkg").read_bytes(), b"new-vector")
        self.assertFalse((self.root / "raster" / "old.tif").exists())
        self.assertFalse((self.root / "vector" / "old.gpkg").exists())
        self.assertEqual(result.file_count, 2)
        self.assertEqual(len(result.sha256), 64)
        self.assertEqual(list(self.root.glob("*.zip")), [])
        self._assert_no_temporary_data()

    def test_resolver_supports_unmanaged_legacy_layout_before_first_activation(self):
        generation = resolve_boundary_generation(self.root)

        self.assertFalse(generation.managed)
        self.assertEqual(generation.generation_id, "legacy-unmanaged")
        self.assertEqual(generation.raster_dir, (self.root / "raster").resolve())
        self.assertEqual(generation.vector_dir, (self.root / "vector").resolve())

    def test_resolver_rejects_unsafe_current_pointer(self):
        (self.root / CURRENT_POINTER_NAME).symlink_to("../outside")

        with self.assertRaises(BoundaryPackageConfigurationError):
            resolve_boundary_generation(self.root)

    def test_resolver_reports_empty_root_without_an_active_package(self):
        empty_root = Path(self.temporary_directory.name) / "empty-boundaries"
        empty_root.mkdir()

        with self.assertRaises(BoundaryGenerationUnavailable):
            resolve_boundary_generation(empty_root)

    def test_fresh_root_gets_compatibility_links_without_legacy_copy(self):
        fresh_root = Path(self.temporary_directory.name) / "fresh-boundaries"
        fresh_root.mkdir()

        result = replace_boundary_package(
            _archive([("raster/new.tif", b"new"), ("vector/new.gpkg", b"new")]),
            fresh_root,
        )

        self.assertTrue((fresh_root / "raster").is_symlink())
        self.assertTrue((fresh_root / "vector").is_symlink())
        self.assertTrue((fresh_root / CURRENT_POINTER_NAME).is_symlink())
        self.assertEqual(
            os.readlink(fresh_root / CURRENT_POINTER_NAME),
            f"{GENERATIONS_DIRECTORY_NAME}/{result.generation_id}",
        )
        self.assertFalse((fresh_root / LEGACY_BACKUPS_DIRECTORY_NAME).exists())
        self.assertFalse(
            any(
                path.name.startswith("legacy-")
                for path in (fresh_root / GENERATIONS_DIRECTORY_NAME).iterdir()
            )
        )
        self.assertEqual(resolve_boundary_generation(fresh_root).generation_id, result.generation_id)

    def test_malformed_zip_never_touches_live_directories(self):
        with self.assertRaises(BoundaryPackageInvalid):
            replace_boundary_package(io.BytesIO(b"this is not a zip"), self.root)

        self._assert_old_package_is_active()
        self._assert_no_temporary_data()

    def test_corrupt_deflate_stream_is_a_typed_invalid_package_error(self):
        archive = _archive(
            [("raster/corrupt.tif", b"compressible content" * 100)],
            compression=ZIP_DEFLATED,
        )

        with self.assertRaises(BoundaryPackageInvalid):
            replace_boundary_package(_corrupt_first_member(archive), self.root)

        self._assert_old_package_is_active()
        self._assert_no_temporary_data()

    def test_rejects_traversal_absolute_backslash_and_unexpected_roots(self):
        unsafe_names = (
            "../escape.tif",
            "/raster/absolute.tif",
            "raster/../../escape.tif",
            "raster/./ambiguous.tif",
            "raster//ambiguous.tif",
            "raster\\..\\escape.tif",
            "C:/raster/drive.tif",
            "Raster/wrong-case.tif",
            "raster/control\nname.tif",
            "raster",
            "unexpected/file.tif",
        )
        for name in unsafe_names:
            with self.subTest(name=name):
                with self.assertRaises(BoundaryPackageUnsafe):
                    replace_boundary_package(_archive([(name, b"unsafe")]), self.root)
                self._assert_old_package_is_active()
                self._assert_no_temporary_data()

    def test_rejects_symlinks_and_special_entries(self):
        for file_type in (stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR):
            with self.subTest(file_type=file_type):
                entry = ZipInfo("raster/unsafe")
                entry.create_system = 3
                entry.external_attr = (file_type | 0o777) << 16
                with self.assertRaises(BoundaryPackageUnsafe):
                    replace_boundary_package(_archive([(entry, b"target")]), self.root)
                self._assert_old_package_is_active()
                self._assert_no_temporary_data()

    def test_rejects_duplicate_casefolded_and_unicode_normalized_paths(self):
        duplicates = (
            [("raster/A.tif", b"one"), ("raster/a.tif", b"two")],
            [("vector/caf\N{LATIN SMALL LETTER E WITH ACUTE}.gpkg", b"one"),
             ("vector/cafe\N{COMBINING ACUTE ACCENT}.gpkg", b"two")],
        )
        for entries in duplicates:
            with self.subTest(entries=entries):
                with self.assertRaises(BoundaryPackageUnsafe):
                    replace_boundary_package(_archive(entries), self.root)
                self._assert_old_package_is_active()
                self._assert_no_temporary_data()

    def test_rejects_file_directory_conflicts(self):
        archive = _archive(
            [("raster/node", b"file"), ("raster/node/child.tif", b"child")]
        )

        with self.assertRaises(BoundaryPackageUnsafe):
            replace_boundary_package(archive, self.root)

        self._assert_old_package_is_active()
        self._assert_no_temporary_data()

    def test_enforces_member_count_member_size_total_size_and_archive_size(self):
        cases = (
            (
                _archive([("raster/a", b"1"), ("vector/b", b"2")]),
                BoundaryPackageLimits(max_members=1),
            ),
            (
                _archive([("raster/a", b"12")]),
                BoundaryPackageLimits(max_member_bytes=1),
            ),
            (
                _archive([("raster/a", b"12"), ("vector/b", b"34")]),
                BoundaryPackageLimits(max_uncompressed_bytes=3),
            ),
            (
                _archive([("raster/a", b"123")]),
                BoundaryPackageLimits(max_archive_bytes=4),
            ),
        )
        for archive, limits in cases:
            with self.subTest(limits=limits):
                with self.assertRaises(BoundaryPackageLimitExceeded):
                    replace_boundary_package(archive, self.root, limits=limits)
                self._assert_old_package_is_active()
                self._assert_no_temporary_data()

    def test_rejects_excessive_compression_ratio(self):
        archive = _archive(
            [("raster/bomb.tif", b"0" * 20_000)],
            compression=ZIP_DEFLATED,
        )
        limits = BoundaryPackageLimits(max_compression_ratio=2)

        with self.assertRaises(BoundaryPackageLimitExceeded):
            replace_boundary_package(archive, self.root, limits=limits)

        self._assert_old_package_is_active()
        self._assert_no_temporary_data()

    def test_rejects_path_components_that_exceed_filesystem_byte_limit(self):
        archive = _archive([("raster/" + "\N{LATIN SMALL LETTER E WITH ACUTE}" * 128, b"x")])

        with self.assertRaises(BoundaryPackageLimitExceeded):
            replace_boundary_package(archive, self.root)

        self._assert_old_package_is_active()
        self._assert_no_temporary_data()

    def test_pinned_reader_keeps_one_generation_across_later_activation(self):
        first = replace_boundary_package(
            _archive([("raster/version.tif", b"one"), ("vector/version.gpkg", b"one")]),
            self.root,
        )
        pinned = resolve_boundary_generation(self.root)

        second = replace_boundary_package(
            _archive([("raster/version.tif", b"two"), ("vector/version.gpkg", b"two")]),
            self.root,
        )
        current = resolve_boundary_generation(self.root)

        self.assertEqual(pinned.generation_id, first.generation_id)
        self.assertEqual(current.generation_id, second.generation_id)
        self.assertNotEqual(pinned.generation_id, current.generation_id)
        self.assertEqual((pinned.raster_dir / "version.tif").read_bytes(), b"one")
        self.assertEqual((pinned.vector_dir / "version.gpkg").read_bytes(), b"one")
        self.assertEqual((current.raster_dir / "version.tif").read_bytes(), b"two")
        self.assertEqual((current.vector_dir / "version.gpkg").read_bytes(), b"two")

    def test_failed_pointer_replace_keeps_old_generation_and_retains_new_one(self):
        first = replace_boundary_package(
            _archive([("raster/version.tif", b"one")]),
            self.root,
        )
        before = resolve_boundary_generation(self.root)
        generations_dir = self.root / GENERATIONS_DIRECTORY_NAME
        generations_before = set(generations_dir.iterdir())
        real_replace = os.replace

        def fail_current_pointer(source, destination):
            destination_path = Path(destination)
            if (
                destination_path.name == CURRENT_POINTER_NAME
                and destination_path.parent.resolve() == self.root.resolve()
            ):
                raise OSError("simulated atomic pointer failure")
            return real_replace(source, destination)

        with patch(
            "qc_tool.frontend.dashboard.services.boundaries.storage.os.replace",
            side_effect=fail_current_pointer,
        ):
            with self.assertRaises(BoundaryPackagePromotionError):
                replace_boundary_package(
                    _archive([("raster/version.tif", b"two")]),
                    self.root,
                )

        after = resolve_boundary_generation(self.root)
        retained = set(generations_dir.iterdir()) - generations_before
        self.assertEqual(before.generation_id, first.generation_id)
        self.assertEqual(after.generation_id, before.generation_id)
        self.assertEqual((after.raster_dir / "version.tif").read_bytes(), b"one")
        self.assertEqual(len(retained), 1)
        retained_generation = retained.pop()
        self.assertEqual((retained_generation / "raster" / "version.tif").read_bytes(), b"two")
        self._assert_no_temporary_data()

    def test_legacy_directories_are_migrated_and_retained_without_deletion(self):
        result = replace_boundary_package(
            _archive([("raster/new.tif", b"new-raster"), ("vector/new.gpkg", b"new-vector")]),
            self.root,
        )

        self.assertTrue((self.root / "raster").is_symlink())
        self.assertTrue((self.root / "vector").is_symlink())
        self.assertTrue((self.root / CURRENT_POINTER_NAME).is_symlink())
        self.assertEqual((self.root / "raster" / "new.tif").read_bytes(), b"new-raster")

        legacy_generations = [
            path
            for path in (self.root / GENERATIONS_DIRECTORY_NAME).iterdir()
            if path.name.startswith("legacy-")
        ]
        self.assertEqual(len(legacy_generations), 1)
        self.assertEqual(
            (legacy_generations[0] / "raster" / "old.tif").read_bytes(),
            b"old-raster",
        )
        backup = self.root / LEGACY_BACKUPS_DIRECTORY_NAME / legacy_generations[0].name
        self.assertEqual((backup / "raster" / "old.tif").read_bytes(), b"old-raster")
        self.assertEqual((backup / "vector" / "old.gpkg").read_bytes(), b"old-vector")
        self.assertEqual(resolve_boundary_generation(self.root).generation_id, result.generation_id)

    def test_interrupted_legacy_exchange_is_safe_and_resumes_on_retry(self):
        from qc_tool.frontend.dashboard.services.boundaries.legacy import _atomic_exchange

        exchange_count = 0

        def interrupt_second_exchange(left, right):
            nonlocal exchange_count
            exchange_count += 1
            if exchange_count == 2:
                raise OSError("simulated unsupported second exchange")
            return _atomic_exchange(left, right)

        with patch(
            "qc_tool.frontend.dashboard.services.boundaries.legacy._atomic_exchange",
            side_effect=interrupt_second_exchange,
        ):
            with self.assertRaises(BoundaryPackageConfigurationError):
                replace_boundary_package(
                    _archive([("raster/unused.tif", b"unused")]),
                    self.root,
                )

        during_recovery = resolve_boundary_generation(self.root)
        self.assertTrue(during_recovery.generation_id.startswith("legacy-"))
        self.assertEqual((self.root / "raster" / "old.tif").read_bytes(), b"old-raster")
        self.assertEqual((self.root / "vector" / "old.gpkg").read_bytes(), b"old-vector")

        completed = replace_boundary_package(
            _archive([("raster/retried.tif", b"retried")]),
            self.root,
        )

        self.assertTrue((self.root / "raster").is_symlink())
        self.assertTrue((self.root / "vector").is_symlink())
        self.assertEqual(resolve_boundary_generation(self.root).generation_id, completed.generation_id)
        self.assertEqual((self.root / "raster" / "retried.tif").read_bytes(), b"retried")

    def test_rejects_symlink_live_target_without_following_it(self):
        outside = Path(self.temporary_directory.name) / "outside"
        outside.mkdir()
        (outside / "keep.tif").write_bytes(b"outside")
        shutil.rmtree(self.root / "raster")
        (self.root / "raster").symlink_to(outside, target_is_directory=True)

        with self.assertRaises(BoundaryPackageConfigurationError):
            replace_boundary_package(
                _archive([("raster/new.tif", b"new")]),
                self.root,
            )

        self.assertEqual((outside / "keep.tif").read_bytes(), b"outside")
        self.assertFalse((outside / "new.tif").exists())
        self._assert_no_temporary_data()

    def test_published_generation_is_group_readable_and_immutable(self):
        replace_boundary_package(
            _archive([("raster/nested/new.tif", b"new")]),
            self.root,
        )

        self.assertEqual(stat.S_IMODE((self.root / "raster").stat().st_mode), 0o550)
        self.assertEqual(
            stat.S_IMODE((self.root / "raster" / "nested").stat().st_mode),
            0o550,
        )
        self.assertEqual(
            stat.S_IMODE((self.root / "raster" / "nested" / "new.tif").stat().st_mode),
            0o440,
        )

    def test_exception_string_never_exposes_diagnostic_detail(self):
        error = BoundaryPackageError("/private/storage/path and traceback detail")

        self.assertEqual(str(error), error.user_message)
        self.assertNotIn("/private/storage", str(error))

    def test_unexpected_processing_error_is_wrapped_for_safe_http_handling(self):
        with patch(
            "qc_tool.frontend.dashboard.services.boundaries.service.copy_archive_bounded",
            side_effect=KeyError("sensitive implementation detail"),
        ):
            with self.assertRaises(BoundaryPackageInternalError) as raised:
                replace_boundary_package(
                    _archive([("raster/new.tif", b"new")]),
                    self.root,
                )

        self.assertNotIn("sensitive", str(raised.exception))
        self._assert_old_package_is_active()
        self._assert_no_temporary_data()

    def test_rejects_non_finite_safety_configuration(self):
        with self.assertRaises(ValueError):
            BoundaryPackageLimits(max_compression_ratio=float("nan"))
        with self.assertRaises(ValueError):
            replace_boundary_package(
                _archive([("raster/new.tif", b"new")]),
                self.root,
                lock_timeout=float("nan"),
            )

    def test_interprocess_lock_times_out_without_touching_live_package(self):
        context = multiprocessing.get_context("fork")
        ready = context.Event()
        release = context.Event()
        process = context.Process(
            target=_hold_boundary_lock,
            args=(str(self.root), ready, release),
        )
        process.start()
        try:
            self.assertTrue(ready.wait(2), "child process did not acquire the lock")
            started = time.monotonic()
            with self.assertRaises(BoundaryPackageBusy):
                replace_boundary_package(
                    _archive([("raster/new.tif", b"new")]),
                    self.root,
                    lock_timeout=0.05,
                )
            self.assertLess(time.monotonic() - started, 1)
        finally:
            release.set()
            process.join(2)
            if process.is_alive():
                process.terminate()
                process.join(2)

        self.assertEqual(process.exitcode, 0)
        self._assert_old_package_is_active()
        self._assert_no_temporary_data()
