"""Native backup files use the same bounded, create-only restoration journal."""

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

from qc_tool.database.transfers import postgres, recovery_files, service
from qc_tool.database.transfers.archive import ArtifactSource, ArchiveLimits, inspect_archive, write_archive
from qc_tool.database.transfers.errors import TransferError
from qc_tool.database.tests.integration.test_transfer_postgres import metadata


class RecoveryFileTests(SimpleTestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.roots = {key: self.root / key for key in ("incoming", "work", "submissions", "boundaries")}
        for path in self.roots.values():
            path.mkdir()
        owner = self.roots["incoming"] / "old-owner"
        owner.mkdir()
        (owner / "old.zip").write_bytes(b"historical unlinked ZIP")
        (owner / "uploads").mkdir()
        (owner / "uploads" / "partial.part").write_bytes(b"temporary")
        job = self.roots["work"] / ("job_" + "a" * 32)
        job.mkdir()
        (job / "report.html").write_bytes(b"original report")
        (job / "job.log").write_bytes(b"diagnostic secret")
        (self.roots["work"] / "maintenance").mkdir()
        (self.roots["work"] / "maintenance" / "state.json").write_bytes(b"private control")

    def package(self):
        inventory, entries, _fingerprint, _size = recovery_files.snapshot(limits=ArchiveLimits(), roots=self.roots)
        dump = self.root / "database.dump"
        dump.write_bytes(b"PGDMPfixture")
        path = self.root / "bundle.zip"
        write_archive(path, {"profile": "database"}, metadata(dump.read_bytes()),
            (ArtifactSource("database", "archive.dump", dump), *inventory.sources),
            directories=inventory.directories, storage=inventory.storage,
            expected_artifacts=[{"root": "database", "key": "archive.dump", "sha256": metadata()["dump_sha256"],
                                 "size": metadata()["dump_bytes"]}, *entries])
        return inspect_archive(path)

    def test_inventory_preserves_old_unlinked_zip_and_reports_without_private_runtime_files(self):
        archive = self.package()
        self.assertEqual({(entry["root"], entry["key"]) for entry in archive.entries}, {
            ("database", "archive.dump"), ("incoming", "old-owner/old.zip"),
            ("work", "job_" + "a" * 32 + "/report.html"),
        })
        postgres._native_metadata(archive)

    def test_create_only_file_restore_is_idempotent_and_does_not_replace_conflicting_zip(self):
        archive = self.package()
        targets = {key: self.root / ("target-" + key) for key in self.roots}
        plan = recovery_files.plan_restore(archive, roots=targets, journal_path=self.root / "files.json")
        plan.apply()
        target = targets["incoming"] / "old-owner" / "old.zip"
        inode = target.stat().st_ino
        recovery_files.plan_restore(archive, roots=targets, journal_path=self.root / "files.json").apply()
        self.assertEqual(target.stat().st_ino, inode)
        target.write_bytes(b"different incumbent bytes")
        with self.assertRaises(TransferError):
            recovery_files.plan_restore(archive, roots=targets, journal_path=self.root / "files.json")
        self.assertEqual(target.read_bytes(), b"different incumbent bytes")

    def test_records_only_restore_does_not_create_any_business_storage(self):
        targets = {key: self.root / ("absent-" + key) for key in self.roots}
        plan = recovery_files.plan_restore(self.package(), roots=targets, journal_path=self.root / "files.json", include_files=False)
        plan.apply()
        self.assertFalse(any(path.exists() for path in targets.values()))

    def test_native_metadata_cannot_authorize_an_arbitrary_work_path(self):
        archive = self.package()
        malicious = {**archive.entries[1], "root": "work", "key": "maintenance/state.json"}
        with self.assertRaises(TransferError):
            postgres._native_metadata(replace(archive, entries=(archive.entries[0], malicious)))

    def test_link_in_retained_namespace_is_rejected(self):
        (self.roots["incoming"] / "old-owner" / "evil.zip").symlink_to(self.root / "outside")
        with self.assertRaises(TransferError):
            recovery_files.collect(roots=self.roots)

    def test_reviewed_hash_is_enforced_before_archive_publication(self):
        inventory, entries, _fingerprint, _size = recovery_files.snapshot(limits=ArchiveLimits(), roots=self.roots)
        inventory.sources[0].path.write_bytes(b"changed after review")
        path = self.root / "stale.zip"
        with self.assertRaisesMessage(TransferError, "files changed after review"):
            write_archive(path, {}, {}, inventory.sources, expected_artifacts=entries)
        self.assertFalse(path.exists())

    def test_inventory_limit_is_enforced_during_collection(self):
        with self.assertRaisesMessage(TransferError, "inventory limit"):
            recovery_files.collect(roots=self.roots, limits=ArchiveLimits(max_members=3))

    def test_export_capacity_reports_limits_and_free_space_before_queueing(self):
        with patch.object(service, "_limits", return_value=ArchiveLimits(max_archive_bytes=10)), \
                patch.object(service, "_require_space", side_effect=TransferError("low space")):
            blockers = service._export_capacity(11)
        self.assertEqual(len(blockers), 2)
        self.assertTrue(all("records only" in message for message in blockers))

    def test_legacy_boundaries_and_specifications_restore_without_activation(self):
        for name in ("raster", "vector"):
            directory = self.roots["boundaries"] / name
            directory.mkdir()
            (directory / "original.bin").write_bytes(name.encode())
        definitions = self.roots["work"] / "product_definitions"
        definitions.mkdir()
        (definitions / "example.json").write_bytes(b'{"description":"original"}')
        (definitions / ".state").mkdir()
        (definitions / ".state" / "example.json").write_bytes(b'{"active":true}')
        archive = self.package()
        self.assertFalse(any("/.state/" in item["key"] for item in archive.entries))
        targets = {key: self.root / ("inert-" + key) for key in self.roots}
        recovery_files.plan_restore(archive, roots=targets, journal_path=self.root / "files.json").apply()
        self.assertFalse((targets["boundaries"] / "raster").exists())
        self.assertFalse((targets["boundaries"] / ".boundary-current").exists())
        self.assertEqual(len(list((targets["boundaries"] / ".boundary-generations").rglob("original.bin"))), 2)
        self.assertFalse((targets["work"] / "product_definitions" / "example.json").exists())
        self.assertEqual(len(list((targets["work"] / "product_definitions" / ".versions").rglob("*.json"))), 1)
