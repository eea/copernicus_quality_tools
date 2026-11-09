"""Job layout changes preserve archive identities, bytes and restoration behavior."""

from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from django.test import SimpleTestCase, override_settings

from qc_tool.database.tests.integration import test_transfer_recovery_files as recovery_fixture
from qc_tool.database.transfers import recovery_files, storage_pins, store
from qc_tool.database.transfers.archive import inspect_archive, write_archive
from qc_tool.database.transfers.artifact_references import validate_reference_inventory
from qc_tool.database.transfers.artifacts import additive_archive, collect_artifacts, plan_artifact_restore
from qc_tool.jobs import create_job_paths, record_job_context, resolve_job_paths


class JobLayoutTransferTests(SimpleTestCase):
    setUp = recovery_fixture.RecoveryFileTests.setUp
    package = recovery_fixture.RecoveryFileTests.package

    def canonical(self, *, filename=None):
        self.identity = str(uuid4())
        paths = create_job_paths(self.roots["work"], self.identity)
        recipe = b'{\n "description": "Original recipe", "steps": []\n}\n'
        filename = filename or sha256(recipe).hexdigest() + ".json"
        record_job_context(paths, specification_filename=filename, specification_sha256=sha256(recipe).hexdigest())
        paths.specification_path(filename).write_bytes(recipe)
        paths.result_path.write_bytes(b'{"status":"ok","report_filename":"original_report.pdf"}')
        paths.report_path("original_report.pdf").write_bytes(b"original PDF bytes")
        (paths.output_dir / "nested").mkdir()
        (paths.output_dir / "nested/attachment.bin").write_bytes(b"native attachment")
        paths.worker_log_path.write_bytes(b"diagnostic excluded")
        return paths, filename

    def payload(self):
        return {"profile": "application", "accounts": [{"key": 1, "username": "old-owner"}], "records": {
            "deliveries": [{"id": 1, "user_id": 1, "s3_id": None, "filename": "old.zip",
                            "size_bytes": len(b"historical unlinked ZIP"), "content_sha256": None,
                            "is_deleted": False}],
            "jobs": [{"job_uuid": self.identity, "delivery_id": 1, "product_ident": "example",
                      "input_sha256": None}],
        }}

    def test_portable_roundtrip_keeps_original_bytes_and_canonical_paths(self):
        paths, filename = self.canonical()
        originals = {p.relative_to(paths.directory): p.read_bytes() for p in paths.directory.rglob("*") if p.is_file()}
        inventory = collect_artifacts(self.payload(), roots=self.roots, include_files=True)
        prefix = "job_" + UUID(self.identity).hex
        keys = {s.key for s in inventory.sources}
        self.assertEqual(keys, {prefix + "/" + name for name in (
            "job.json", "result.json", "specification/" + filename, "reports/original_report.pdf", "outputs/nested/attachment.bin")}
            | {"old-owner/old.zip"})
        package = self.root / "canonical-portable.zip"
        write_archive(package, {}, self.payload(), inventory.sources, directories=inventory.directories, storage=inventory.storage)
        archive = inspect_archive(package)
        validate_reference_inventory(archive)
        targets = {key: self.root / "portable-target" / key for key in self.roots}
        journal = self.root / "portable-journal.json"
        plan_artifact_restore(archive, roots=targets, journal_path=journal).apply()
        restored = resolve_job_paths(targets["work"], self.identity)
        self.assertFalse(restored.legacy)
        for relative, content in originals.items():
            if relative.parts[0] != "logs":
                self.assertEqual((restored.directory / relative).read_bytes(), content)
        self.assertEqual(list(restored.logs_dir.iterdir()), [])
        self.assertFalse((targets["work"] / prefix).exists())
        plan_artifact_restore(archive, roots=targets, journal_path=journal).apply()
        self.assertEqual(paths.metadata_path.read_bytes(), originals[Path("job.json")])

    def test_native_roundtrip_and_original_source_pin_use_exact_physical_paths(self):
        paths, filename = self.canonical()
        archive = self.package(components=["artifacts"])
        targets = {key: self.root / "native-target" / key for key in self.roots}
        journal = self.root / "native-journal.json"
        plan = recovery_files.plan_restore(archive, roots=targets, journal_path=journal)
        with override_settings(QC_TOOL_TRANSFER_DIR=self.root / "private-transfers"):
            operation = {"id": str(uuid4()), "destination": {"database": "candidate"}}
            store.operation_dir(operation["id"], create=True)
            pin = storage_pins.pin_restore_files(operation, plan)
            physical = {Path(pin["roots"][e["root"]]) / e["key"] for e in pin["files"]}
            self.assertIn(targets["work"] / self.identity / "specification" / filename, physical)
            self.assertIn(targets["work"] / self.identity / "outputs/nested/attachment.bin", physical)
        plan.apply()
        recovery_files.plan_restore(archive, roots=targets, journal_path=journal).apply()
        restored = resolve_job_paths(targets["work"], self.identity)
        self.assertEqual(restored.metadata_path.read_bytes(), paths.metadata_path.read_bytes())
        self.assertEqual(restored.specification_path(filename).read_bytes(), paths.specification_path(filename).read_bytes())
        # The pre-existing native fixture remains exactly at its historical name.
        self.assertTrue((targets["work"] / ("job_" + "a" * 32) / "report.html").is_file())

    def test_archive_cannot_use_other_json_as_recipe_or_redirect_context_identity(self):
        paths, filename = self.canonical()
        (paths.specification_dir / "unrelated.json").write_bytes(b"{}")
        with self.assertRaisesMessage(ValueError, "unrecognized artifact"):
            collect_artifacts(self.payload(), roots=self.roots)
        (paths.specification_dir / "unrelated.json").unlink()
        paths.specification_path(filename).write_bytes(b"different recipe")
        with self.assertRaisesMessage(ValueError, "immutable context"):
            collect_artifacts(self.payload(), roots=self.roots)

    def test_specification_named_job_json_remains_separate_from_producer_metadata(self):
        paths, filename = self.canonical(filename="job.json")
        archive = self.package(components=["artifacts"])
        targets = {key: self.root / "collision-target" / key for key in self.roots}
        recovery_files.plan_restore(archive, roots=targets, journal_path=self.root / "collision.json").apply()
        restored = resolve_job_paths(targets["work"], self.identity)
        self.assertEqual(restored.metadata_path.read_bytes(), paths.metadata_path.read_bytes())
        self.assertEqual(restored.specification_path(filename).read_bytes(), paths.specification_path(filename).read_bytes())
        self.assertNotEqual(restored.metadata_path.read_bytes(), restored.specification_path(filename).read_bytes())

    def test_canonical_payload_refuses_an_existing_legacy_location_without_changes(self):
        self.canonical()
        archive = self.package(components=["artifacts"])
        targets = {key: self.root / "legacy-target" / key for key in self.roots}
        retained = targets["work"] / ("job_" + UUID(self.identity).hex)
        retained.mkdir(parents=True)
        marker = retained / "original.json"
        marker.write_bytes(b"retained legacy bytes")
        with self.assertRaisesMessage(ValueError, "existing legacy"):
            recovery_files.plan_restore(archive, roots=targets, journal_path=self.root / "refused.json")
        self.assertEqual(marker.read_bytes(), b"retained legacy bytes")
        self.assertFalse((targets["work"] / self.identity).exists())

    def test_records_only_references_do_not_require_packaged_producer_context(self):
        self.canonical()
        inventory = collect_artifacts(self.payload(), roots=self.roots, include_files=False)
        package = self.root / "records-only.zip"
        write_archive(package, {}, self.payload(), inventory.sources,
                      directories=inventory.directories, storage=inventory.storage)
        archive = inspect_archive(package)
        validate_reference_inventory(archive)
        self.assertEqual(archive.entries, ())

    def test_additive_selection_retains_validated_canonical_payload_namespaces(self):
        self.canonical()
        inventory = collect_artifacts(self.payload(), roots=self.roots, include_files=True)
        package = self.root / "additive.zip"
        write_archive(package, {}, self.payload(), inventory.sources,
                      directories=inventory.directories, storage=inventory.storage)
        archive = inspect_archive(package)
        selected = additive_archive(archive, {"deliveries": [1], "jobs": [self.identity]})
        self.assertEqual({(item["root"], item["key"]) for item in selected.entries},
                         {(item["root"], item["key"]) for item in archive.entries})

    def test_legacy_payload_refuses_to_overlay_an_existing_canonical_job(self):
        self.canonical()
        archive = self.package(components=["artifacts"])
        targets = {key: self.root / "mixed-target" / key for key in self.roots}
        # This archive also includes the native legacy fixture job with UUID a*32.
        retained = create_job_paths(targets["work"], "a" * 32)
        before = retained.metadata_path.read_bytes()
        with self.assertRaisesMessage(ValueError, "existing canonical"):
            recovery_files.plan_restore(archive, roots=targets, journal_path=self.root / "mixed.json")
        self.assertEqual(retained.metadata_path.read_bytes(), before)

    def test_interrupted_restore_reuses_canonical_mapping_before_context_publication(self):
        paths, filename = self.canonical()
        archive = self.package(components=["artifacts"])
        targets = {key: self.root / "interrupted-target" / key for key in self.roots}
        journal = self.root / "interrupted.json"
        plan = recovery_files.plan_restore(archive, roots=targets, journal_path=journal)
        original = type(plan.archive).copy_artifact
        def interrupt(instance, entry, stream):
            if entry["root"] == "work" and entry["key"].endswith("/job.json"):
                raise OSError("Simulated interruption before metadata publication")
            return original(instance, entry, stream)
        with patch.object(type(plan.archive), "copy_artifact", interrupt):
            with self.assertRaises(OSError):
                plan.apply(rollback_on_error=False)
        self.assertFalse((targets["work"] / self.identity / "job.json").exists())
        recovery_files.plan_restore(archive, roots=targets, journal_path=journal).apply()
        restored = resolve_job_paths(targets["work"], self.identity)
        self.assertEqual(restored.specification_path(filename).read_bytes(), paths.specification_path(filename).read_bytes())
