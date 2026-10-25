"""Compression planning preserves reviewed source bytes and restore identities."""

from dataclasses import replace
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import zipfile

from django.test import SimpleTestCase

from qc_tool.database.transfers import recovery_files, service
from qc_tool.database.transfers.archive import (
    ArchiveLimits, ArtifactSource, inspect_archive, write_archive,
)
from qc_tool.database.transfers.artifacts import ArtifactInventory


class CompressionSnapshotTests(SimpleTestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.boundaries = self.root / "boundaries"
        (self.boundaries / "raster").mkdir(parents=True)
        self.original = b"original boundary mask values\x00\x01" * 65_536
        self.path = self.boundaries / "raster" / "mask.tif"
        self.path.write_bytes(self.original)
        self.limits = replace(ArchiveLimits(), max_archive_bytes=64 * 1024)

    def test_native_inventory_keeps_original_identity_while_compressed_package_fits(self):
        inventory, entries, fingerprint, byte_count = recovery_files.snapshot(
            roots={"boundaries": self.boundaries}, components=["boundaries"], limits=self.limits)
        self.assertGreater(byte_count, self.limits.max_archive_bytes)
        self.assertEqual(byte_count, len(self.original))
        self.assertEqual(entries, [{"root": "boundaries", "key": "raster/mask.tif",
                                   "size": len(self.original),
                                   "sha256": hashlib.sha256(self.original).hexdigest()}])
        source = inventory.sources[0]
        self.assertEqual(source.compression.compress_type, zipfile.ZIP_DEFLATED)
        self.assertLess(source.compression.compressed_bytes, self.limits.max_archive_bytes)
        self.assertNotIn("compression", repr(inventory.storage))

        package = self.root / "backup.zip"
        write_archive(package, {"profile": "database"}, {}, inventory.sources,
                      directories=inventory.directories, storage=inventory.storage,
                      expected_artifacts=entries, limits=self.limits)
        verified = inspect_archive(package, limits=self.limits)
        self.assertEqual(verified.entries[0]["sha256"], entries[0]["sha256"])
        with zipfile.ZipFile(package) as archive:
            self.assertEqual(archive.read(verified.entries[0]["path"]), self.original)
        self.assertEqual(self.path.read_bytes(), self.original)

        # A receiver with a stricter ratio policy selects storage instead, but
        # the review still identifies exactly the same original files.
        stored, stored_entries, stored_fingerprint, stored_bytes = recovery_files.snapshot(
            roots={"boundaries": self.boundaries}, components=["boundaries"],
            limits=replace(self.limits, max_compression_ratio=1))
        self.assertEqual(stored.sources[0].compression.compress_type, zipfile.ZIP_STORED)
        self.assertEqual((stored_entries, stored_fingerprint, stored_bytes),
                         (entries, fingerprint, byte_count))

    def test_portable_review_hash_does_not_depend_on_compression_policy(self):
        payload = {"profile": "application", "created_at": "2026-10-23T00:00:00Z",
                   "accounts": [], "records": {}, "contract": "fixture"}
        source = ArtifactSource("boundaries", "raster/mask.tif", self.path, self.boundaries)
        inventory = ArtifactInventory(sources=(source,))
        selection = {"profile": "application", "user_ids": [], "include_files": True}
        snapshots = []
        with patch.object(service, "export_records", return_value=payload), \
                patch.object(service, "collect_artifacts", return_value=inventory):
            for limits in (self.limits, replace(self.limits, max_compression_ratio=1)):
                with patch.object(service, "_limits", return_value=limits):
                    snapshots.append(service._snapshot(selection))
        compressed, stored = snapshots
        self.assertEqual(compressed[1].sources[0].compression.compress_type, zipfile.ZIP_DEFLATED)
        self.assertEqual(stored[1].sources[0].compression.compress_type, zipfile.ZIP_STORED)
        self.assertEqual(compressed[2:], stored[2:])
        self.assertEqual(set(compressed[4][0]), {"root", "key", "size", "sha256"})

