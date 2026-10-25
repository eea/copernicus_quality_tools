"""Export progress follows bounded I/O without changing package contents."""

from contextlib import contextmanager
import hashlib
import io
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import Mock, call, patch

from django.test import SimpleTestCase

from qc_tool.database.transfers import postgres, recovery_files
from qc_tool.database.transfers.archive import (
    ArchiveLimits, ArtifactSource, BLOCK_SIZE, _hash, inspect_archive,
    write_archive, write_native_archive,
)


class ExportChunkProgressTests(SimpleTestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.data = b"original file bytes\n" * (BLOCK_SIZE // 10)

    def test_hash_reads_fixed_chunks_and_reports_cumulative_bytes(self):
        class Source(io.BytesIO):
            def read(self, size=-1):
                self_test.assertEqual(size, BLOCK_SIZE)
                return super().read(size)

        self_test, progress = self, []
        actual = _hash(Source(self.data), len(self.data), report=progress.append)
        self.assertEqual(actual, (hashlib.sha256(self.data).hexdigest(), len(self.data)))
        self.assertGreater(len(progress), 1)
        self.assertEqual(progress, sorted(progress))
        self.assertEqual(progress[-1], len(self.data))
        self.assertTrue(all(right - left <= BLOCK_SIZE for left, right in zip([0, *progress], progress)))

    def test_portable_and_native_writers_report_copy_then_complete_package_verification(self):
        source = self.root / "original.zip"
        source.write_bytes(self.data)
        artifact = ArtifactSource("incoming", "operator/original.zip", source)
        expected = [{"root": artifact.root, "key": artifact.key,
                     "sha256": hashlib.sha256(self.data).hexdigest(), "size": len(self.data)}]
        dump = b"PGDMPfixture"

        def capture(stream):
            stream.write(dump)
            return {"dump_sha256": hashlib.sha256(dump).hexdigest(), "dump_bytes": len(dump),
                    "_package_sections": {"schema/schema.sql": b"x" * (BLOCK_SIZE + 1)}}

        for native in (False, True):
            with self.subTest(native=native):
                progress = []
                path = self.root / ("native.zip" if native else "portable.zip")
                writer = write_native_archive if native else write_archive
                checksum = writer(path, {}, capture if native else {}, [artifact],
                                  expected_artifacts=expected,
                                  report=lambda phase, **values: progress.append((phase, values)))
                self.assertEqual(checksum, inspect_archive(path).package_sha256)
                self.assertEqual({phase for phase, _values in progress}, {"copy_files", "verify_package"})
                copied = [values for phase, values in progress if phase == "copy_files"]
                verified = [values for phase, values in progress if phase == "verify_package"]
                self.assertEqual(copied[-1], {"processed_bytes": len(self.data), "total_bytes": len(self.data),
                                              "processed_items": 1, "total_items": 1})
                self.assertGreater(len(copied), 2)
                self.assertEqual(verified[-1], {"processed_bytes": path.stat().st_size,
                                                "total_bytes": path.stat().st_size})
                self.assertGreater(len(verified), 2)
                self.assertNotIn(str(self.root), repr(progress))

    def test_recovery_review_reports_inventory_and_hash_chunks_without_paths(self):
        incoming = self.root / "incoming"
        (incoming / "operator").mkdir(parents=True)
        (incoming / "operator" / "original.zip").write_bytes(self.data)
        progress = []
        _inventory, entries, _fingerprint, byte_count = recovery_files.snapshot(
            limits=ArchiveLimits(), roots={"incoming": incoming}, components=["deliveries"],
            report=lambda phase, **values: progress.append((phase, values)))
        self.assertEqual(byte_count, len(self.data))
        self.assertEqual(entries[0]["sha256"], hashlib.sha256(self.data).hexdigest())
        self.assertEqual(progress[0], ("scan_files", {"processed_items": 0}))
        hashing = [values for phase, values in progress if phase == "hash_files"]
        self.assertGreater(len(hashing), 2)
        self.assertEqual(hashing[-1], {"processed_bytes": len(self.data), "processed_items": 1, "total_items": 1})
        self.assertNotIn("original.zip", repr(progress))


class PostgresInventoryBatchTests(SimpleTestCase):
    def test_catalog_identity_cursor_fetches_bounded_batches_without_fetchall(self):
        handle, cursor = Mock(), Mock()
        handle.cursor.return_value.__enter__ = Mock(return_value=cursor)
        handle.cursor.return_value.__exit__ = Mock(return_value=False)
        cursor.fetchmany.side_effect = [[("first",)], [("second",)], []]
        self.assertEqual(list(postgres._catalog_rows(handle, "SELECT identities")), [("first",), ("second",)])
        self.assertTrue(handle.cursor.call_args.kwargs["name"].startswith("qc_backup_"))
        self.assertEqual(cursor.itersize, 256)
        self.assertEqual(cursor.fetchmany.call_args_list, [call(256)] * 3)
        cursor.fetchall.assert_not_called()

    def test_row_inventory_keeps_exact_hashes_and_caps_server_sort_resources(self):
        cursor, handle = Mock(), Mock()

        @contextmanager
        def cursors():
            yield cursor

        handle.cursor.side_effect = cursors
        cursor.fetchall.return_value = [("value", "text", False, "", "")]
        blocks = [b'{"value":"one"}\n', b'{"value":"two"}\n']

        def copy(_statement, output):
            for block in blocks:
                output.write(block)

        cursor.copy_expert.side_effect = copy
        progress = []
        with patch.object(postgres, "_catalog_rows", side_effect=[[(1, "public", "example", "r", True)], []]), \
                patch.object(postgres, "_schema_hash", return_value="a" * 64), \
                patch.object(postgres, "_sequences", return_value=[]):
            inventory = postgres._inventory(handle, {}, {}, "snapshot",
                report=lambda phase, **values: progress.append((phase, values)))
        self.assertIn(call("SET LOCAL work_mem = '16MB'"), cursor.execute.call_args_list)
        self.assertIn(call("SET LOCAL max_parallel_workers_per_gather = 0"), cursor.execute.call_args_list)
        self.assertEqual(inventory["tables"][0]["sha256"], hashlib.sha256(b"".join(blocks)).hexdigest())
        self.assertEqual(inventory["total_rows"], 2)
        self.assertEqual(progress[-1], ("inventory_database", {
            "processed_bytes": sum(map(len, blocks)), "processed_items": 1}))

    def test_postgresql_pipe_reports_cumulative_streamed_output(self):
        destination, progress = io.BytesIO(), []
        postgres._run_tool([sys.executable, "-c", "import sys;sys.stdout.buffer.write(b'x'*200000)"],
            output_stream=destination, max_bytes=200000,
            report=lambda phase, **values: progress.append((phase, values)), phase="database_dump")
        self.assertEqual(len(destination.getvalue()), 200000)
        self.assertEqual(progress[0], ("database_dump", {"processed_bytes": 0}))
        self.assertEqual(progress[-1], ("database_dump", {"processed_bytes": 200000}))
        self.assertEqual([values["processed_bytes"] for _phase, values in progress],
                         sorted(values["processed_bytes"] for _phase, values in progress))
