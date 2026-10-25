"""Storage ZIP downloads preserve files without disk copies or unsafe traversal."""

from contextlib import contextmanager
from io import BytesIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZIP_STORED, ZipFile

from django.test import SimpleTestCase, override_settings

from qc_tool.common import CONFIG
from qc_tool.frontend.dashboard.services.storage_admin import downloads, files


class StorageDownloadTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.root = Path(self.enterContext(TemporaryDirectory(prefix="qc-storage-download-")))
        self.incoming, self.work = self.root / "incoming", self.root / "work"
        self.incoming.mkdir()
        self.work.mkdir()
        self.enterContext(patch.dict(CONFIG, work_dir=self.work, incoming_dir=self.incoming,
                                    submission_dir=None, boundary_dir=self.root / "boundaries", product_dirs=[]))
        self.enterContext(override_settings(MEDIA_ROOT=self.incoming,
            S3_CREDENTIALS_DIR=self.root / "credentials", QC_TOOL_MAINTENANCE_DIR=self.root / "maintenance",
            QC_TOOL_TRANSFER_DIR=self.root / "transfers"))
        self.folder = self.incoming / "alice"
        self.folder.mkdir()
        (self.folder / "report.txt").write_bytes(b"report bytes\x00\xff")
        (self.folder / "empty").mkdir()

    def archive(self, plan):
        return ZipFile(BytesIO(b"".join(downloads.stream_zip(plan))))

    def test_streamed_archive_is_readable_with_crc_files_empty_folders_and_report(self):
        plan = downloads.prepare_zip("incoming", ["alice"])
        self.assertEqual((plan.filename, plan.file_count, plan.directory_count, plan.total_bytes),
                         ("alice.zip", 1, 2, len(b"report bytes\x00\xff")))
        with self.archive(plan) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.read("files/alice/report.txt"), b"report bytes\x00\xff")
            self.assertTrue(archive.getinfo("files/alice/empty/").is_dir())
            self.assertIn("This is a copy of files, not a database backup.", archive.read(downloads.REPORT_NAME).decode())
            self.assertTrue(all(entry.compress_type == ZIP_STORED for entry in archive.infolist()))

    def test_preparation_never_opens_or_reads_file_contents(self):
        with patch.object(files, "open_file", side_effect=AssertionError("unexpected data read")):
            plan = downloads.prepare_zip("incoming", ["alice"])
        self.assertEqual(plan.file_count, 1)

    def test_parent_selections_include_descendants_only_once(self):
        plan = downloads.prepare_zip("incoming", ["alice/report.txt", "alice", "alice"])
        self.assertEqual(plan.selected_paths, ("alice",))
        with self.archive(plan) as archive:
            self.assertEqual(archive.namelist().count("files/alice/report.txt"), 1)
        self.assertEqual(downloads.prepare_zip("incoming", ["", "alice"]).selected_paths, ("",))

    def test_root_download_and_source_report_name_cannot_collide(self):
        (self.incoming / downloads.REPORT_NAME).write_bytes(b"original user report")
        plan = downloads.prepare_zip("incoming", [""])
        self.assertEqual(plan.filename, "storage-incoming.zip")
        with self.archive(plan) as archive:
            self.assertEqual(archive.read("files/" + downloads.REPORT_NAME), b"original user report")
            self.assertIn(b"QC Tool storage download", archive.read(downloads.REPORT_NAME))

    def test_private_linked_special_and_nonportable_descendants_are_reported_not_read(self):
        outside = self.root / "secret"
        outside.write_bytes(b"SECRET-CONTENTS-DO-NOT-DISCLOSE")
        (self.folder / "symbolic.txt").symlink_to(outside)
        os.link(outside, self.folder / "hard.txt")
        os.mkfifo(self.folder / "fifo")
        for name in (".hidden", "AUX.txt", "windows:stream", "trailing. "):
            (self.folder / name).write_bytes(b"SECRET-CONTENTS-DO-NOT-DISCLOSE")
        plan = downloads.prepare_zip("incoming", ["alice"])
        self.assertEqual(plan.excluded_count, 7)
        content = b"".join(downloads.stream_zip(plan))
        self.assertNotIn(b"SECRET-CONTENTS-DO-NOT-DISCLOSE", content)
        with ZipFile(BytesIO(content)) as archive:
            report = archive.read(downloads.REPORT_NAME).decode()
            self.assertIn("Excluded entries: 7", report)
            self.assertIn("symbolic.txt", report)
            self.assertNotIn(str(self.root), report)

    def test_explicit_unsafe_selection_is_rejected_before_response(self):
        for path in ("../secret", "/etc/passwd", "alice/.hidden", "alice/windows:stream"):
            with self.subTest(path=path), self.assertRaises(files.StorageError):
                downloads.prepare_zip("incoming", [path])

    def test_entry_and_selection_limits_fail_instead_of_returning_partial_plan(self):
        with patch.object(downloads, "MAX_ARCHIVE_ENTRIES", 2), self.assertRaisesMessage(files.StorageError, "10,000"):
            downloads.prepare_zip("incoming", ["alice"])
        # Repeated duplicate selections still count towards the input limit.
        with self.assertRaisesMessage(files.StorageError, "100"):
            downloads.prepare_zip("incoming", ["alice"] * 101)
        for invalid in ([], "alice", None):
            with self.subTest(invalid=invalid), self.assertRaises(files.StorageError):
                downloads.prepare_zip("incoming", invalid)
        with patch.object(downloads, "MAX_PATH_METADATA_BYTES", 5), self.assertRaisesMessage(files.StorageError, "metadata limit"):
            downloads.prepare_zip("incoming", ["alice"])

    def test_application_root_includes_original_files_but_reports_private_descendants(self):
        (self.work / "notes.txt").write_bytes(b"retained working file")
        definitions = self.work / "product_definitions"
        definitions.mkdir()
        original = b"original specification bytes; never rewritten"
        (definitions / "original.pdf").write_bytes(original)
        control = self.work / "shared" / "private"
        control.mkdir(parents=True)
        (control / "state.json").write_bytes(b"DO-NOT-DOWNLOAD-PRIVATE-CONTROL")
        (self.work / "worker.token").write_bytes(b"DO-NOT-DOWNLOAD-PRIVATE-TOKEN")
        with override_settings(QC_TOOL_TRANSFER_DIR=control):
            plan = downloads.prepare_zip("work", [""])
            content = b"".join(downloads.stream_zip(plan))
        self.assertEqual(plan.excluded_count, 2)
        self.assertNotIn(b"DO-NOT-DOWNLOAD-PRIVATE", content)
        with ZipFile(BytesIO(content)) as archive:
            self.assertEqual(archive.read("files/product_definitions/original.pdf"), original)
            self.assertEqual(archive.read("files/notes.txt"), b"retained working file")
            self.assertIn(b"shared/private", archive.read(downloads.REPORT_NAME))
        self.assertEqual((definitions / "original.pdf").read_bytes(), original)

    def test_file_replacement_after_preflight_aborts_zip(self):
        plan = downloads.prepare_zip("incoming", ["alice/report.txt"])
        source = self.folder / "report.txt"
        source.unlink()
        source.write_bytes(b"other bytes")
        with self.assertRaisesMessage(files.StorageError, "changed"):
            b"".join(downloads.stream_zip(plan))

    def test_path_swap_to_symlink_after_preflight_never_reads_outside(self):
        plan = downloads.prepare_zip("incoming", ["alice/report.txt"])
        source = self.folder / "report.txt"
        source.unlink()
        source.symlink_to(self.root / "outside")
        with self.assertRaises(files.StorageError):
            b"".join(downloads.stream_zip(plan))

    def test_chunk_reads_are_bounded_and_cancel_closes_source_without_worker(self):
        payload = b"x" * (downloads.CHUNK_BYTES * 4)
        (self.folder / "large.bin").write_bytes(payload)
        plan = downloads.prepare_zip("incoming", ["alice/large.bin"])
        opened, reads = [], []
        original_open = files.open_file

        class TrackedFile:
            def __init__(self, handle):
                self.handle = handle
            def fileno(self):
                return self.handle.fileno()
            def read(self, size):
                reads.append(size)
                return self.handle.read(size)

        @contextmanager
        def tracked_open(*args):
            with original_open(*args) as handle:
                opened.append(handle)
                yield TrackedFile(handle)

        with patch.object(files, "open_file", tracked_open):
            stream = downloads.stream_zip(plan)
            while not reads:
                next(stream)
            self.assertFalse(opened[0].closed)
            self.assertEqual(reads, [downloads.CHUNK_BYTES])
            stream.close()
        self.assertTrue(opened[0].closed)
        self.assertEqual(len(reads), 1)

    def test_file_modified_during_stream_aborts_before_valid_central_directory(self):
        source = self.folder / "large.bin"
        source.write_bytes(b"x" * (downloads.CHUNK_BYTES * 2))
        plan = downloads.prepare_zip("incoming", ["alice/large.bin"])
        stream = downloads.stream_zip(plan)
        chunks = []
        while True:
            chunk = next(stream)
            chunks.append(chunk)
            if chunk == b"x" * downloads.CHUNK_BYTES:
                break
        with source.open("r+b") as handle:
            handle.write(b"changed")
        with self.assertRaisesMessage(files.StorageError, "changed"):
            chunks.extend(stream)
        self.assertNotIn(b"PK\x05\x06", b"".join(chunks))

    def test_zip64_header_is_used_even_for_small_files(self):
        plan = downloads.prepare_zip("incoming", ["alice/report.txt"])
        with self.archive(plan) as archive:
            self.assertGreaterEqual(archive.getinfo("files/alice/report.txt").extract_version, 45)

    def test_windows_names_with_decomposed_unicode_are_never_rewritten_in_archive(self):
        (self.folder / "cafe\u0301.txt").write_bytes(b"original")
        plan = downloads.prepare_zip("incoming", ["alice"])
        self.assertEqual(plan.excluded_count, 1)
        with self.archive(plan) as archive:
            self.assertNotIn("files/alice/caf\u00e9.txt", archive.namelist())

    def test_case_colliding_files_fail_preflight_instead_of_excluding_or_overwriting(self):
        first, second = self.folder / "Report.txt", self.folder / "report.TXT"
        first.write_bytes(b"first original")
        second.write_bytes(b"second original")
        with self.assertRaises(files.StorageError) as raised:
            downloads.prepare_zip("incoming", ["alice"])
        self.assertEqual(raised.exception.code, "archive_name_collision")
        self.assertIn("Report.txt", str(raised.exception))
        self.assertIn("report.TXT", str(raised.exception))
        self.assertIn("Download these items separately", str(raised.exception))
        self.assertEqual(first.read_bytes(), b"first original")
        self.assertEqual(second.read_bytes(), b"second original")

    def test_colliding_explicit_directory_components_fail_through_recursive_walk(self):
        for folder_name, file_name in (("Foo", "a.txt"), ("foo", "b.txt")):
            folder = self.folder / "nested" / folder_name
            folder.mkdir(parents=True, exist_ok=True)
            (folder / file_name).write_bytes(b"original")
        with self.assertRaises(files.StorageError) as raised:
            downloads.prepare_zip("incoming", ["alice"])
        self.assertEqual(raised.exception.code, "archive_name_collision")
        self.assertIn("alice/nested/Foo", str(raised.exception))
        self.assertIn("alice/nested/foo", str(raised.exception))

    def test_selected_files_cannot_merge_implicit_parent_folders_on_extraction(self):
        for folder_name, file_name in (("Foo", "a.txt"), ("foo", "b.txt")):
            folder = self.folder / folder_name
            folder.mkdir()
            (folder / file_name).write_bytes(b"original")
        with self.assertRaises(files.StorageError) as raised:
            downloads.prepare_zip("incoming", ["alice/Foo/a.txt", "alice/foo/b.txt"])
        self.assertEqual(raised.exception.code, "archive_name_collision")
        self.assertIn("alice/Foo", str(raised.exception))
        self.assertIn("alice/foo", str(raised.exception))

    def test_unicode_casefold_and_normalization_equivalent_names_fail_preflight(self):
        # Both source names are NFC, but casefolding the second Greek name
        # produces a decomposed sequence equivalent to the first name.
        for name in ("\u0390.txt", "\u03aa\u0301.txt"):
            files._parts("incoming", "alice/" + name, allow_empty=False)
            (self.folder / name).write_bytes(name.encode("utf-8"))
        with self.assertRaises(files.StorageError) as raised:
            downloads.prepare_zip("incoming", ["alice"])
        self.assertEqual(raised.exception.code, "archive_name_collision")

    def test_distinct_names_and_shared_exact_parent_preserve_original_paths(self):
        (self.folder / "REPORT-2.txt").write_bytes(b"second original")
        plan = downloads.prepare_zip("incoming", ["alice/report.txt", "alice/REPORT-2.txt"])
        with self.archive(plan) as archive:
            self.assertEqual(archive.read("files/alice/report.txt"), b"report bytes\x00\xff")
            self.assertEqual(archive.read("files/alice/REPORT-2.txt"), b"second original")
