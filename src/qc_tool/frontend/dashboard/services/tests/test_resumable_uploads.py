from __future__ import annotations

import multiprocessing
from pathlib import Path
import stat
import tempfile
from unittest import TestCase

from qc_tool.frontend.dashboard.services.uploads import (
    ResumableUploadDescriptor,
    ResumableUploadError,
    assemble_chunks,
    expected_chunk_paths,
    is_chunk_stored,
    is_upload_complete,
    prepare_resumable_paths,
    remove_published_upload,
    store_chunk,
)
from qc_tool.frontend.dashboard.services.uploads._resumable.locks import upload_lock


class _UploadedChunk:
    def __init__(self, *parts, advertised_size=None, on_chunks=None):
        self._parts = parts
        self.size = (
            sum(len(part) for part in parts)
            if advertised_size is None
            else advertised_size
        )
        self._on_chunks = on_chunks

    def chunks(self):
        if self._on_chunks is not None:
            self._on_chunks()
        yield from self._parts


class _MultiValueMapping:
    def __init__(self, values):
        self._values = values

    def getlist(self, name):
        value = self._values.get(name, [])
        return value if isinstance(value, list) else [value]


def _parameters(
    *,
    identifier="upload-1",
    filename="delivery.zip",
    chunk_number=1,
    chunk_size=5,
    current_chunk_size=4,
    total_chunks=1,
    total_size=4,
):
    return {
        "resumableIdentifier": str(identifier),
        "resumableFilename": filename,
        "resumableChunkNumber": str(chunk_number),
        "resumableChunkSize": str(chunk_size),
        "resumableCurrentChunkSize": str(current_chunk_size),
        "resumableTotalChunks": str(total_chunks),
        "resumableTotalSize": str(total_size),
    }


def _descriptor(**overrides):
    return ResumableUploadDescriptor.from_mapping(_parameters(**overrides))


def _hold_upload_lock(chunks_dir, ready, release):
    with upload_lock(Path(chunks_dir), timeout=2):
        ready.set()
        release.wait(5)


class ResumableDescriptorTests(TestCase):
    def test_accepts_the_bundled_clients_single_and_multi_chunk_layouts(self):
        single = _descriptor()
        first = _descriptor(
            chunk_number=1,
            current_chunk_size=5,
            total_chunks=2,
            total_size=12,
        )
        last = _descriptor(
            chunk_number=2,
            current_chunk_size=7,
            total_chunks=2,
            total_size=12,
        )

        self.assertEqual(single.expected_size_for_chunk(1), 4)
        self.assertEqual(first.expected_size_for_chunk(1), 5)
        self.assertEqual(last.expected_size_for_chunk(2), 7)
        self.assertEqual(first.storage_key, last.storage_key)

    def test_rejects_traversal_and_non_zip_filenames(self):
        for filename in (
            "../delivery.zip",
            "/tmp/delivery.zip",
            "nested/delivery.zip",
            "nested\\delivery.zip",
            "delivery.txt",
            "bad\nname.zip",
            "\ud800.zip",
        ):
            with self.subTest(filename=filename):
                with self.assertRaises(ResumableUploadError) as caught:
                    _descriptor(filename=filename)
                self.assertEqual(caught.exception.code, "invalid_delivery_filename")

    def test_rejects_unsafe_identifiers_and_ambiguous_parameters(self):
        for identifier in ("../escape", "with.dot", "", "a" * 201):
            with self.subTest(identifier=identifier):
                with self.assertRaises(ResumableUploadError) as caught:
                    _descriptor(identifier=identifier)
                self.assertEqual(caught.exception.code, "invalid_upload_identifier")

        duplicated = _parameters()
        duplicated["resumableIdentifier"] = ["upload-1", "upload-2"]
        with self.assertRaises(ResumableUploadError) as caught:
            ResumableUploadDescriptor.from_mapping(_MultiValueMapping(duplicated))
        self.assertEqual(caught.exception.code, "invalid_upload_parameters")

    def test_rejects_noncanonical_numbers_and_inconsistent_layouts(self):
        for value in ("0", "-1", "+1", " 1", "1.0", "1" * 13):
            values = _parameters()
            values["resumableChunkNumber"] = value
            with self.subTest(value=value):
                with self.assertRaises(ResumableUploadError) as caught:
                    ResumableUploadDescriptor.from_mapping(values)
                self.assertEqual(caught.exception.code, "invalid_upload_parameters")

        inconsistent = (
            {"chunk_number": 2},
            {"total_chunks": 2},
            {"current_chunk_size": 3},
        )
        for overrides in inconsistent:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ResumableUploadError):
                    _descriptor(**overrides)

    def test_enforces_chunk_count_chunk_size_and_total_size_bounds(self):
        cases = (
            (
                {"total_chunks": 25_001},
                "invalid_chunk_number",
                400,
            ),
            (
                {"chunk_size": 64 * 1024 * 1024 + 1},
                "upload_chunk_too_large",
                413,
            ),
            (
                {"total_size": 100 * 1024 * 1024 * 1024 + 1},
                "delivery_too_large",
                413,
            ),
        )
        for overrides, code, status_code in cases:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ResumableUploadError) as caught:
                    _descriptor(**overrides)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(caught.exception.status_code, status_code)


class ResumablePathTests(TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.media_root = Path(self.temporary_directory.name) / "media"
        self.media_root.mkdir()
        self.descriptor = _descriptor()

    def test_creates_private_confined_staging_paths(self):
        paths = prepare_resumable_paths(
            self.descriptor,
            media_root=self.media_root,
            username="alice@example.test",
        )

        self.assertEqual(paths.user_root.parent, self.media_root.resolve())
        self.assertEqual(paths.target_path, paths.user_root / "delivery.zip")
        self.assertEqual(paths.chunks_dir.name, self.descriptor.storage_key)
        self.assertNotIn(self.descriptor.identifier, paths.chunks_dir.name)
        self.assertEqual(stat.S_IMODE(paths.chunks_dir.stat().st_mode), 0o700)

    def test_read_only_probe_does_not_create_directories(self):
        paths = prepare_resumable_paths(
            self.descriptor,
            media_root=self.media_root,
            username="alice",
            create=False,
        )

        self.assertFalse(paths.user_root.exists())
        self.assertFalse(paths.chunks_dir.exists())
        self.assertFalse(is_chunk_stored(paths.chunk_path))

    def test_rejects_owner_traversal_before_creating_any_path(self):
        outside = self.media_root.parent / "escape"
        for username in (
            "../escape",
            "/tmp/escape",
            "nested/user",
            "nested\\user",
            "\ud800",
        ):
            with self.subTest(username=username):
                with self.assertRaises(ResumableUploadError) as caught:
                    prepare_resumable_paths(
                        self.descriptor,
                        media_root=self.media_root,
                        username=username,
                    )
                self.assertEqual(caught.exception.code, "invalid_upload_owner")
        self.assertFalse(outside.exists())

    def test_rejects_symlinked_storage_directories(self):
        outside = self.media_root.parent / "outside"
        outside.mkdir()
        (self.media_root / "alice").symlink_to(outside, target_is_directory=True)

        for create in (False, True):
            with self.subTest(create=create):
                with self.assertRaises(ResumableUploadError) as caught:
                    prepare_resumable_paths(
                        self.descriptor,
                        media_root=self.media_root,
                        username="alice",
                        create=create,
                    )
                self.assertEqual(caught.exception.code, "unsafe_upload_storage")

    def test_upload_wide_metadata_is_bound_to_the_staging_directory(self):
        original = prepare_resumable_paths(
            self.descriptor,
            media_root=self.media_root,
            username="alice",
        )
        changed = prepare_resumable_paths(
            _descriptor(filename="other.zip"),
            media_root=self.media_root,
            username="alice",
        )

        self.assertNotEqual(original.chunks_dir, changed.chunks_dir)


class ResumableStorageTests(TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.media_root = Path(self.temporary_directory.name) / "media"
        self.media_root.mkdir()
        self.descriptor = _descriptor()
        self.paths = prepare_resumable_paths(
            self.descriptor,
            media_root=self.media_root,
            username="alice",
        )

    def _temporary_uploads(self):
        return list(self.paths.chunks_dir.glob("*.uploading")) + list(
            self.paths.chunks_dir.glob(".*.uploading")
        )

    def test_chunk_is_not_visible_until_its_complete_contents_are_durable(self):
        def assert_not_published():
            self.assertFalse(self.paths.chunk_path.exists())

        created = store_chunk(
            _UploadedChunk(b"ab", b"cd", on_chunks=assert_not_published),
            self.paths.chunk_path,
            expected_bytes=4,
        )

        self.assertTrue(created)
        self.assertEqual(self.paths.chunk_path.read_bytes(), b"abcd")
        self.assertTrue(is_chunk_stored(self.paths.chunk_path))
        self.assertTrue(is_upload_complete(self.descriptor, self.paths))
        self.assertEqual(stat.S_IMODE(self.paths.chunk_path.stat().st_mode), 0o600)
        self.assertEqual(self._temporary_uploads(), [])

    def test_identical_duplicate_is_idempotent_but_different_duplicate_conflicts(self):
        self.assertTrue(
            store_chunk(
                _UploadedChunk(b"abcd"),
                self.paths.chunk_path,
                expected_bytes=4,
            )
        )
        self.assertFalse(
            store_chunk(
                _UploadedChunk(b"abcd"),
                self.paths.chunk_path,
                expected_bytes=4,
            )
        )

        with self.assertRaises(ResumableUploadError) as caught:
            store_chunk(
                _UploadedChunk(b"wxyz"),
                self.paths.chunk_path,
                expected_bytes=4,
            )
        self.assertEqual(caught.exception.code, "duplicate_chunk_conflict")
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.paths.chunk_path.read_bytes(), b"abcd")

    def test_rejects_empty_wrong_sized_and_oversized_chunks_without_partial_files(self):
        cases = (
            (_UploadedChunk(), {"expected_bytes": None}, "empty_upload_chunk"),
            (
                _UploadedChunk(b"abc"),
                {"expected_bytes": 4},
                "invalid_upload_chunk_size",
            ),
            (
                _UploadedChunk(b"abcd", advertised_size=-1),
                {"max_chunk_bytes": 3},
                "upload_chunk_too_large",
            ),
        )
        for uploaded, options, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(ResumableUploadError) as caught:
                    store_chunk(uploaded, self.paths.chunk_path, **options)
                self.assertEqual(caught.exception.code, code)
                self.assertFalse(self.paths.chunk_path.exists())
                self.assertEqual(self._temporary_uploads(), [])

    def test_never_follows_an_existing_chunk_symlink(self):
        outside = self.media_root.parent / "outside.bin"
        outside.write_bytes(b"outside")
        self.paths.chunk_path.symlink_to(outside)

        with self.assertRaises(ResumableUploadError) as caught:
            store_chunk(
                _UploadedChunk(b"abcd"),
                self.paths.chunk_path,
                expected_bytes=4,
            )

        self.assertEqual(caught.exception.code, "unsafe_upload_staging")
        self.assertEqual(outside.read_bytes(), b"outside")
        with self.assertRaises(ResumableUploadError):
            is_chunk_stored(self.paths.chunk_path)

    def test_never_follows_a_staging_directory_replaced_by_a_symlink(self):
        outside = self.media_root.parent / "outside-staging"
        outside.mkdir()
        self.paths.chunks_dir.rmdir()
        self.paths.chunks_dir.symlink_to(outside, target_is_directory=True)

        with self.assertRaises(ResumableUploadError) as caught:
            store_chunk(
                _UploadedChunk(b"abcd"),
                self.paths.chunk_path,
                expected_bytes=4,
            )

        self.assertEqual(caught.exception.code, "unsafe_upload_storage")
        self.assertEqual(list(outside.iterdir()), [])

    def test_assembles_exact_chunk_sizes_and_removes_chunk_content(self):
        first = _descriptor(
            chunk_number=1,
            current_chunk_size=5,
            total_chunks=2,
            total_size=12,
        )
        second = _descriptor(
            chunk_number=2,
            current_chunk_size=7,
            total_chunks=2,
            total_size=12,
        )
        first_paths = prepare_resumable_paths(
            first,
            media_root=self.media_root,
            username="bob",
        )
        second_paths = prepare_resumable_paths(
            second,
            media_root=self.media_root,
            username="bob",
        )
        store_chunk(
            _UploadedChunk(b"first"),
            first_paths.chunk_path,
            expected_bytes=5,
        )
        store_chunk(
            _UploadedChunk(b"-second"),
            second_paths.chunk_path,
            expected_bytes=7,
        )

        target = assemble_chunks(second, second_paths)

        self.assertEqual(target.read_bytes(), b"first-second")
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o640)
        self.assertTrue(
            all(not path.exists() for path in expected_chunk_paths(second, second_paths))
        )

    def test_assembly_rejects_missing_and_wrong_sized_chunks(self):
        with self.assertRaises(ResumableUploadError) as caught:
            assemble_chunks(self.descriptor, self.paths)
        self.assertEqual(caught.exception.code, "upload_incomplete")

        self.paths.chunk_path.write_bytes(b"abc")
        with self.assertRaises(ResumableUploadError) as caught:
            assemble_chunks(self.descriptor, self.paths)
        self.assertEqual(caught.exception.code, "invalid_upload_chunk_size")
        self.assertFalse(self.paths.target_path.exists())

    def test_assembly_never_overwrites_an_existing_delivery(self):
        self.paths.target_path.write_bytes(b"existing")
        store_chunk(
            _UploadedChunk(b"abcd"),
            self.paths.chunk_path,
            expected_bytes=4,
        )

        with self.assertRaises(ResumableUploadError) as caught:
            assemble_chunks(self.descriptor, self.paths)

        self.assertEqual(caught.exception.code, "delivery_file_exists")
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.paths.target_path.read_bytes(), b"existing")
        self.assertEqual(self.paths.chunk_path.read_bytes(), b"abcd")

    def test_assembly_lock_timeout_does_not_touch_the_upload(self):
        store_chunk(
            _UploadedChunk(b"abcd"),
            self.paths.chunk_path,
            expected_bytes=4,
        )
        ready = multiprocessing.Event()
        release = multiprocessing.Event()
        process = multiprocessing.Process(
            target=_hold_upload_lock,
            args=(str(self.paths.chunks_dir), ready, release),
        )
        process.start()
        self.addCleanup(lambda: process.kill() if process.is_alive() else None)
        self.assertTrue(ready.wait(2))

        try:
            with self.assertRaises(ResumableUploadError) as caught:
                assemble_chunks(self.descriptor, self.paths, lock_timeout=0.01)
        finally:
            release.set()
            process.join(2)

        self.assertEqual(caught.exception.code, "upload_busy")
        self.assertEqual(caught.exception.status_code, 409)
        self.assertFalse(self.paths.target_path.exists())
        self.assertEqual(self.paths.chunk_path.read_bytes(), b"abcd")

    def test_assembly_does_not_follow_chunk_symlinks(self):
        outside = self.media_root.parent / "outside.bin"
        outside.write_bytes(b"abcd")
        self.paths.chunk_path.symlink_to(outside)

        with self.assertRaises(ResumableUploadError):
            assemble_chunks(self.descriptor, self.paths)

        self.assertFalse(self.paths.target_path.exists())
        self.assertEqual(outside.read_bytes(), b"abcd")

    def test_assembly_refuses_a_staging_directory_replaced_by_a_symlink(self):
        store_chunk(
            _UploadedChunk(b"abcd"),
            self.paths.chunk_path,
            expected_bytes=4,
        )
        original_staging = self.paths.chunks_dir.with_name("original-staging")
        self.paths.chunks_dir.rename(original_staging)
        outside = self.media_root.parent / "outside-staging"
        outside.mkdir()
        (outside / self.paths.chunk_path.name).write_bytes(b"evil")
        self.paths.chunks_dir.symlink_to(outside, target_is_directory=True)

        with self.assertRaises(ResumableUploadError) as caught:
            assemble_chunks(self.descriptor, self.paths)

        self.assertEqual(caught.exception.code, "unsafe_upload_storage")
        self.assertFalse(self.paths.target_path.exists())
        self.assertEqual((outside / self.paths.chunk_path.name).read_bytes(), b"evil")

    def test_cleanup_removes_only_the_exact_published_regular_file(self):
        store_chunk(
            _UploadedChunk(b"abcd"),
            self.paths.chunk_path,
            expected_bytes=4,
        )
        target = assemble_chunks(self.descriptor, self.paths)

        self.assertTrue(remove_published_upload(self.paths, target))
        self.assertFalse(target.exists())
        self.assertFalse(remove_published_upload(self.paths, target))

        unrelated = self.paths.user_root / "unrelated.zip"
        unrelated.write_bytes(b"keep")
        with self.assertRaises(ResumableUploadError) as caught:
            remove_published_upload(self.paths, unrelated)
        self.assertEqual(caught.exception.code, "unsafe_upload_cleanup")
        self.assertEqual(unrelated.read_bytes(), b"keep")

    def test_cleanup_refuses_a_symlink_at_the_published_path(self):
        outside = self.media_root.parent / "outside.zip"
        outside.write_bytes(b"outside")
        self.paths.target_path.symlink_to(outside)

        with self.assertRaises(ResumableUploadError) as caught:
            remove_published_upload(self.paths, self.paths.target_path)

        self.assertEqual(caught.exception.code, "unsafe_upload_cleanup")
        self.assertTrue(self.paths.target_path.is_symlink())
        self.assertEqual(outside.read_bytes(), b"outside")
