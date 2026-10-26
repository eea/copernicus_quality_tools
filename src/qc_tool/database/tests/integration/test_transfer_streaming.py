"""Bounded backup streams use one private archive and retain reader compatibility."""

from contextlib import contextmanager, nullcontext
from dataclasses import replace
import hashlib
import io
import os
from pathlib import Path
import sys
import zipfile
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

from qc_tool.database.transfers import archive, postgres
from qc_tool.database.transfers.archive import (
    ArchiveLimits, ArtifactSource, TransferArchiveError, canonical_json,
    compressed_sizes, estimate_archive_size, hash_with_compression, inspect_archive,
    write_archive, write_native_archive,
)
from qc_tool.database.transfers.errors import TransferError


class StreamingArchiveTests(SimpleTestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.path = self.root / "backup.zip"
        self.data = b"PGDMP" + bytes(range(256)) * 1024
        self.metadata = {"dump_sha256": hashlib.sha256(self.data).hexdigest(), "dump_bytes": len(self.data)}

    def capture(self, stream):
        for offset in range(0, len(self.data), 4096):
            stream.write(self.data[offset:offset + 4096])
        return self.metadata

    def native_entry(self):
        return {"root": "database", "key": "data/database.dump", "sha256": self.metadata["dump_sha256"],
                "size": len(self.data)}

    def test_native_roundtrip_uses_the_existing_reader_without_an_intermediate_dump(self):
        extra = self.root / "source.zip"
        extra.write_bytes(b"original input bytes")
        source = ArtifactSource("incoming", "operator/input.zip", extra)
        growth = []
        checksum = write_native_archive(self.path, {"description": "native"}, self.capture,
                                        [source], check_space=growth.append)
        verified = inspect_archive(self.path)
        self.assertEqual(verified.records, self.metadata)
        self.assertEqual(verified.package_sha256, checksum)
        self.assertEqual(sum(growth), self.path.stat().st_size)
        with verified.open_artifact(verified.entries[0]) as stream:
            self.assertEqual(stream.read(), self.data)
        self.assertCountEqual([item.name for item in self.root.iterdir()], [extra.name, self.path.name])
        entries = [self.native_entry(), {"root": source.root, "key": source.key,
            "sha256": hashlib.sha256(extra.read_bytes()).hexdigest(), "size": extra.stat().st_size}]
        sizes = estimate_archive_size({"description": "native"}, self.metadata, entries,
                                     artifacts_first=True, format_version=2)
        self.assertEqual(sizes["archive_bytes"], self.path.stat().st_size)
        with zipfile.ZipFile(self.path) as package:
            self.assertEqual(package.namelist()[0], "database/data/database.dump")
            self.assertIn("deliveries/incoming/operator/input.zip", package.namelist())

    def test_supplemental_sections_are_separately_checksummed_and_indexed(self):
        sections = {"schema/schema.sql": b"CREATE SCHEMA example;\n",
                    "metadata/source.json": b'{"database":"source"}'}

        def capture(stream):
            return {**self.capture(stream), "_package_sections": sections}

        write_native_archive(self.path, {}, capture)
        verified = inspect_archive(self.path)
        self.assertNotIn("_package_sections", verified.records)
        self.assertEqual({entry["key"] for entry in verified.records["sections"]}, set(sections))
        with zipfile.ZipFile(self.path) as package:
            for key, payload in sections.items():
                self.assertEqual(package.read("database/" + key), payload)

    def test_unbounded_supplemental_payload_is_rejected_without_publication(self):
        def capture(stream):
            return {**self.capture(stream), "_package_sections": {"schema/schema.sql": b"x" * 300000}}

        with self.assertRaisesMessage(TransferArchiveError, "member exceeds"):
            write_native_archive(self.path, {}, capture,
                                 limits=replace(ArchiveLimits(), max_member_bytes=len(self.data)))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_portable_size_includes_manifest_and_complete_zip_headers(self):
        manifest, records = {"description": "portable"}, {"rows": [1, 2, 3]}
        sizes = estimate_archive_size(manifest, records)
        limits = replace(ArchiveLimits(), max_archive_bytes=sizes["archive_bytes"],
                         max_total_bytes=sizes["expanded_bytes"])
        write_archive(self.path, manifest, records, limits=limits)
        self.assertEqual(self.path.stat().st_size, sizes["archive_bytes"])
        self.assertEqual(inspect_archive(self.path, limits=limits).records, records)
        self.path.unlink()
        with self.assertRaisesMessage(TransferArchiveError, "total size"):
            write_archive(self.path, manifest, records,
                          limits=replace(limits, max_total_bytes=len(canonical_json(records))))
        self.assertFalse(self.path.exists())
        self.assertFalse(list(self.root.glob(".transfer-*")))

    def test_estimator_can_report_an_oversized_package_without_applying_limits(self):
        limits = replace(ArchiveLimits(), max_archive_bytes=1, max_total_bytes=1,
                         max_manifest_bytes=1, max_records_bytes=1, max_member_bytes=1)
        sizes = estimate_archive_size({}, {"rows": [1]}, limits=limits, validate_limits=False)
        self.assertGreater(sizes["archive_bytes"], limits.max_archive_bytes)
        with self.assertRaises(TransferArchiveError):
            estimate_archive_size({}, {"rows": [1]}, limits=limits)

    def test_archive_rejects_central_directory_overflow_before_writing_payload(self):
        with self.assertRaisesMessage(TransferArchiveError, "ZIP metadata"):
            write_archive(self.path, {}, {}, limits=replace(ArchiveLimits(), max_central_directory_bytes=1))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_reserve_failure_stops_stream_and_removes_unpublished_bytes(self):
        total = 0

        def check_space(growth):
            nonlocal total
            total += growth
            if total > 8192:
                raise TransferError("Private backup reserve reached")

        with self.assertRaisesMessage(TransferError, "reserve reached"):
            write_native_archive(self.path, {}, self.capture, check_space=check_space)
        self.assertFalse(self.path.exists())
        self.assertFalse(list(self.root.glob(".transfer-*")))
        self.assertLess(total, len(self.data))

    def test_archive_and_member_bounds_interrupt_stream_before_publication(self):
        for limits in (replace(ArchiveLimits(), max_archive_bytes=8192),
                       replace(ArchiveLimits(), max_member_bytes=8192)):
            with self.subTest(limits=limits), self.assertRaises(TransferArchiveError):
                write_native_archive(self.path, {}, self.capture, limits=limits)
            self.assertEqual(list(self.root.iterdir()), [])

    def test_reviewed_file_changes_of_the_same_size_fail_during_copy(self):
        source = self.root / "input.zip"
        source.write_bytes(b"reviewed")
        entries = [{"root": "incoming", "key": "input.zip", "size": source.stat().st_size,
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]
        source.write_bytes(b"modified")
        with self.assertRaisesMessage(TransferArchiveError, "files changed after review"):
            write_archive(self.path, {}, {}, [ArtifactSource("incoming", "input.zip", source)],
                          expected_artifacts=entries)
        self.assertFalse(self.path.exists())
        self.assertFalse(list(self.root.glob(".transfer-*")))

    def test_native_capture_metadata_must_match_the_streamed_bytes(self):
        def capture(stream):
            stream.write(self.data)
            return {**self.metadata, "dump_sha256": "0" * 64}

        with self.assertRaisesMessage(TransferArchiveError, "integrity verification"):
            write_native_archive(self.path, {}, capture)
        self.assertEqual(list(self.root.iterdir()), [])

    def compressed_source(self, data, *, limits=None):
        path = self.root / "boundary.tif"
        path.write_bytes(data)
        checksum, size, plan = hash_with_compression(io.BytesIO(data), len(data), limits=limits)
        source = ArtifactSource("boundaries", "raster/boundary.tif", path, compression=plan)
        entry = {"root": source.root, "key": source.key, "sha256": checksum, "size": size}
        return source, entry

    def test_compressed_export_fits_limits_and_space_smaller_than_original_files(self):
        data = b"original boundary pixel values\n" * 150_000
        limits = replace(ArchiveLimits(), max_archive_bytes=64 * 1024)
        source, entry = self.compressed_source(data, limits=limits)
        sizes = estimate_archive_size({}, {}, [entry], limits=limits,
                                      compressed_sizes=compressed_sizes([source]))
        self.assertGreater(sizes["expanded_bytes"], limits.max_archive_bytes)
        self.assertLess(sizes["archive_bytes"], limits.max_archive_bytes)
        growth = []

        def check_space(amount):
            growth.append(amount)
            if sum(growth) > limits.max_archive_bytes:
                raise TransferError("Insufficient private backup space")

        write_archive(self.path, {}, {}, [source], expected_artifacts=[entry],
                      limits=limits, check_space=check_space)
        verified = inspect_archive(self.path, limits=limits)
        copied = io.BytesIO()
        verified.copy_artifact(verified.entries[0], copied)
        self.assertEqual(copied.getvalue(), data)
        self.assertEqual(self.path.stat().st_size, sizes["archive_bytes"])
        self.assertEqual(sum(growth), self.path.stat().st_size)
        self.assertFalse(list(self.root.glob(".transfer-*")))
        with zipfile.ZipFile(self.path) as package:
            self.assertEqual(package.getinfo(verified.entries[0]["path"]).compress_type, zipfile.ZIP_DEFLATED)

    def test_direct_writer_plans_compression_without_a_prior_snapshot(self):
        data = b"\0" * (2 * 1024 * 1024)
        source, _entry = self.compressed_source(data)
        limits = replace(ArchiveLimits(), max_archive_bytes=32 * 1024)
        write_archive(self.path, {}, {}, [replace(source, compression=None)], limits=limits)
        verified = inspect_archive(self.path, limits=limits)
        self.assertEqual(verified.entries[0]["size"], len(data))
        self.assertLess(self.path.stat().st_size, limits.max_archive_bytes)

    def test_native_dump_stays_stored_while_optional_files_are_compressed(self):
        data = b"original boundary data\n" * 100_000
        source, entry = self.compressed_source(data)
        limits = replace(ArchiveLimits(), max_archive_bytes=512 * 1024)
        write_native_archive(self.path, {}, self.capture, [source], expected_artifacts=[entry], limits=limits)
        verified = inspect_archive(self.path, limits=limits)
        with zipfile.ZipFile(self.path) as package:
            self.assertEqual(package.getinfo("database/data/database.dump").compress_type, zipfile.ZIP_STORED)
            self.assertEqual(package.getinfo("boundaries/raster/boundary.tif").compress_type, zipfile.ZIP_DEFLATED)
            self.assertEqual(package.read("boundaries/raster/boundary.tif"), data)
        entries = [self.native_entry(), entry]
        sizes = estimate_archive_size({}, self.metadata, entries, limits=limits, artifacts_first=True,
                                      format_version=2, compressed_sizes=compressed_sizes([source], format_version=2))
        self.assertEqual(self.path.stat().st_size, sizes["archive_bytes"])
        self.assertEqual(len(verified.entries), 2)

    def test_compression_falls_back_to_stored_for_incompressible_or_ratio_limited_data(self):
        for data, limits in ((os.urandom(32 * 1024), ArchiveLimits()),
                             (b"\0" * (1024 * 1024), replace(ArchiveLimits(), max_compression_ratio=2))):
            with self.subTest(limit=limits.max_compression_ratio):
                source, entry = self.compressed_source(data, limits=limits)
                self.assertEqual(source.compression.compress_type, zipfile.ZIP_STORED)
                self.assertEqual(source.compression.compressed_bytes, len(data))
                write_archive(self.path, {}, {}, [source], expected_artifacts=[entry], limits=limits)
                self.assertEqual(inspect_archive(self.path, limits=limits).entries[0]["size"], len(data))
                self.path.unlink()

    def test_plan_is_bound_to_original_digest_and_detects_changed_bytes(self):
        source, entry = self.compressed_source(b"a" * 100_000)
        source.path.write_bytes(b"b" * entry["size"])
        with self.assertRaisesMessage(TransferArchiveError, "files changed after review"):
            write_archive(self.path, {}, {}, [source], expected_artifacts=[entry])
        self.assertFalse(self.path.exists())
        self.assertFalse(list(self.root.glob(".transfer-*")))
        entry["sha256"] = "0" * 64
        with self.assertRaisesMessage(TransferArchiveError, "compression plan"):
            write_archive(self.path, {}, {}, [source], expected_artifacts=[entry])

    def test_compressed_files_keep_raw_expanded_and_member_limits(self):
        source, entry = self.compressed_source(b"boundary\n" * 100_000)
        for limits in (replace(ArchiveLimits(), max_total_bytes=entry["size"]),
                       replace(ArchiveLimits(), max_member_bytes=entry["size"] - 1)):
            with self.subTest(limits=limits), self.assertRaises(TransferArchiveError):
                write_archive(self.path, {}, {}, [source], expected_artifacts=[entry], limits=limits)
            self.assertFalse(self.path.exists())

    def test_compressed_zip64_estimate_accounts_for_original_member_size(self):
        source, entry = self.compressed_source(b"boundary\n" * 10_000)
        with patch.object(zipfile, "ZIP64_LIMIT", 1024):
            sizes = estimate_archive_size({}, {}, [entry], compressed_sizes=compressed_sizes([source]))
            write_archive(self.path, {}, {}, [source], expected_artifacts=[entry])
            self.assertEqual(self.path.stat().st_size, sizes["archive_bytes"])
            self.assertEqual(inspect_archive(self.path).entries[0]["size"], entry["size"])

    def test_complete_import_reader_verification_precedes_package_publication(self):
        checked = []

        def inspect_private(path, *, limits):
            self.assertFalse(self.path.exists())
            self.assertTrue(path.name.startswith(".transfer-"))
            self.assertTrue(path.exists())
            checked.append(path)
            return inspect_archive(path, limits=limits)

        with patch.object(archive, "inspect_archive", side_effect=inspect_private):
            write_archive(self.path, {}, {})
        self.assertEqual(len(checked), 1)
        self.assertTrue(self.path.exists())
        self.assertFalse(checked[0].exists())

    def test_corrupt_completed_compressed_stream_is_never_published(self):
        source, entry = self.compressed_source(b"original boundary\n" * 100_000)

        def corrupt_then_inspect(path, *, limits):
            with zipfile.ZipFile(path) as package:
                member = package.getinfo("artifacts/boundaries/raster/boundary.tif")
                self.assertEqual(member.compress_type, zipfile.ZIP_DEFLATED)
            with path.open("r+b") as output:
                output.seek(member.header_offset)
                header = output.read(30)
                payload_offset = (member.header_offset + 30
                                  + int.from_bytes(header[26:28], "little")
                                  + int.from_bytes(header[28:30], "little"))
                output.seek(payload_offset)
                first = output.read(1)[0]
                output.seek(payload_offset)
                # DEFLATE block type 3 is reserved and cannot be decoded.
                output.write(bytes([first | 0x06]))
            return inspect_archive(path, limits=limits)

        with patch.object(archive, "inspect_archive", side_effect=corrupt_then_inspect):
            with self.assertRaisesMessage(TransferArchiveError, "damaged"):
                write_archive(self.path, {}, {}, [source], expected_artifacts=[entry])
        self.assertFalse(self.path.exists())
        self.assertFalse(list(self.root.glob(".transfer-*")))

    def test_reader_failure_or_changed_package_digest_removes_private_output(self):
        for failure in (True, False):
            with self.subTest(reader_failure=failure):
                def inspect_private(path, *, limits):
                    if failure:
                        raise TransferArchiveError("Package failed import validation")
                    return replace(inspect_archive(path, limits=limits), package_sha256="0" * 64)

                with patch.object(archive, "inspect_archive", side_effect=inspect_private):
                    with self.assertRaises(TransferArchiveError):
                        write_archive(self.path, {}, {})
                self.assertFalse(self.path.exists())
                self.assertFalse(list(self.root.glob(".transfer-*")))


class PostgresStreamTests(SimpleTestCase):
    def test_tool_streams_output_without_a_file_descriptor_or_metadata_buffer(self):
        destination = io.BytesIO()
        data = b"x" * 131072
        with patch.object(postgres, "_MAX_DIAGNOSTIC_BYTES", 16):
            postgres._run_tool([sys.executable, "-c", "import sys;sys.stdout.buffer.write(b'x'*131072)"],
                               output_stream=destination, max_bytes=len(data))
        self.assertEqual(destination.getvalue(), data)

    def test_tool_stream_size_is_checked_before_writing_oversized_output(self):
        destination = io.BytesIO()
        with self.assertRaisesMessage(TransferError, "file limit"):
            postgres._run_tool([sys.executable, "-c", "import sys;sys.stdout.buffer.write(b'x'*131072)"],
                               output_stream=destination, max_bytes=1024)
        self.assertLessEqual(len(destination.getvalue()), 1024)

    def test_capture_stream_preserves_snapshot_reconciliation_and_hashes(self):
        destination, data = io.BytesIO(), b"PGDMP streamed fixture"
        info = {"server_major": 14, "snapshot": "1-2-3"}
        inventory = {"tables": [], "sequences": [], "large_objects": [], "total_rows": 0}

        @contextmanager
        def database(*args, **kwargs):
            yield object(), info

        def run(arguments, **kwargs):
            self.assertEqual(arguments[0], "pg_dump")
            self.assertIn("--snapshot=1-2-3", arguments)
            self.assertNotIn("output", kwargs)
            kwargs["output_stream"].write(data[:5])
            kwargs["output_stream"].write(data[5:])

        with patch.object(postgres, "_params", return_value={}), \
                patch.object(postgres, "_database", database), \
                patch.object(postgres, "_toolchain", return_value={"pg_dump": "pg_dump"}), \
                patch.object(postgres, "_inventory", return_value=inventory), \
                patch.object(postgres, "_sequences", return_value=[]), \
                patch.object(postgres, "_tool_environment", return_value=nullcontext({})), \
                patch.object(postgres, "_review", return_value={"review_hash": "a" * 64}), \
                patch.object(postgres, "_supplemental_sections", return_value={}), \
                patch.object(postgres, "_with_preservation"), \
                patch.object(postgres, "_run_tool", side_effect=run):
            metadata = postgres.capture_stream(destination)
        self.assertEqual(destination.getvalue(), data)
        self.assertEqual(metadata["dump_sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(metadata["dump_bytes"], len(data))

    def test_globals_fingerprint_excludes_random_safety_tokens_but_keeps_credentials(self):
        first = b"\\restrict abc\n-- Started on 2026-10-23\nALTER ROLE operator PASSWORD 'hash-one';\n\\unrestrict abc\n"
        second = first.replace(b"abc", b"xyz").replace(b"2026-10-23", b"2026-10-24")
        self.assertEqual(postgres._globals_hash(first), postgres._globals_hash(second))
        self.assertNotEqual(postgres._globals_hash(first), postgres._globals_hash(first.replace(b"hash-one", b"hash-two")))

    def test_selected_globals_failure_is_not_replaced_with_a_partial_backup(self):
        with patch.object(postgres, "_client_tool", side_effect=TransferError("Missing pg_dumpall")):
            with self.assertRaisesMessage(TransferError, "Missing pg_dumpall"):
                postgres._globals_output({}, {"server_major": 14})
