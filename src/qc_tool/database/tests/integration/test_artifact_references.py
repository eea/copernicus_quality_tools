"""Optional bytes must never weaken retained identity or payload validation."""

from copy import deepcopy
from dataclasses import replace
import hashlib
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase, TestCase

from qc_tool.database.transfers.archive import TransferArchiveError, inspect_archive, write_archive
from qc_tool.database.transfers.artifact_references import (
    receipt_references, validate_reference_inventory, without_payloads,
)
from qc_tool.database.transfers.artifacts import (
    additive_archive, collect_artifacts, inspect_delivery_files, inspect_retained_artifact_conflicts, plan_artifact_restore,
)


class ArtifactReferenceTests(SimpleTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.roots = {name: self.root / name for name in ("work", "incoming", "submissions", "boundaries")}
        for directory in self.roots.values():
            directory.mkdir()
        self.content = b"original ZIP bytes"
        self.digest = hashlib.sha256(self.content).hexdigest()
        self.job = str(uuid4())
        self.payload = {"profile": "application", "accounts": [{"key": "1", "username": "alice"}], "records": {
            "deliveries": [{"id": 3, "user_id": 1, "filename": "delivery.zip", "size_bytes": len(self.content),
                            "content_sha256": self.digest, "is_deleted": False, "s3_id": None}],
            "jobs": [{"job_uuid": self.job, "delivery_id": 3, "input_sha256": self.digest}],
        }}
        self.package = self.root / "package.zip"

    def archive(self, include_files):
        inventory = collect_artifacts(self.payload, roots=self.roots, include_files=include_files)
        write_archive(self.package, {}, self.payload, inventory.sources, directories=inventory.directories, storage=inventory.storage)
        return inventory, inspect_archive(self.package)

    def input_file(self, content=None):
        path = self.roots["incoming"] / "alice" / "delivery.zip"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(self.content if content is None else content)
        return path

    def test_records_only_retains_missing_inputs_and_does_not_create_directories(self):
        inventory, archive = self.archive(False)
        self.assertEqual(inventory.sources, ())
        self.assertEqual(archive.entries, ())
        refs = validate_reference_inventory(archive)
        self.assertEqual(refs["mode"], "records_only")
        inputs = [row for row in refs["items"] if row["role"] in {"delivery_input", "job_input"}]
        self.assertEqual(len(inputs), 2)
        self.assertTrue(all(row["expected_sha256"] == self.digest and row["availability"] == "missing" for row in inputs))
        before = list(self.roots["incoming"].iterdir())
        plan = plan_artifact_restore(archive, roots=self.roots)
        plan.apply()
        self.assertEqual(list(self.roots["incoming"].iterdir()), before)

    def test_available_files_allows_absent_source_bytes_but_preserves_expectations(self):
        inventory, archive = self.archive(True)
        self.assertTrue(inventory.warnings)
        validate_reference_inventory(archive)
        self.assertEqual(plan_artifact_restore(archive, roots=self.roots).summary["create_files"], 0)

    def test_records_only_recognizes_retained_exact_zip_without_rewriting_it(self):
        path = self.input_file()
        before = path.stat().st_ino
        _inventory, archive = self.archive(False)
        inspection = inspect_delivery_files(archive, roots=self.roots)
        self.assertEqual(inspection["conflicts"], [])
        self.assertEqual(inspection["files"][0]["status"], "retained_verified")
        self.assertEqual(path.stat().st_ino, before)

    def test_wrong_retained_zip_is_warning_for_records_only_and_not_overwritten(self):
        path = self.input_file(b"different bytes")
        _inventory, archive = self.archive(False)
        inspection = inspect_delivery_files(archive, roots=self.roots)
        self.assertEqual(inspection["conflicts"], [])
        self.assertEqual(inspection["files"][0]["status"], "different")
        plan_artifact_restore(archive, roots=self.roots).apply()
        self.assertEqual(path.read_bytes(), b"different bytes")

    def test_legacy_strict_contract_still_requires_active_input(self):
        with self.assertRaises(TransferArchiveError):
            collect_artifacts(self.payload, roots=self.roots)

    def test_included_payload_must_have_matching_declared_reference(self):
        self.input_file()
        _inventory, archive = self.archive(True)
        validate_reference_inventory(archive)
        altered = deepcopy(archive.storage)
        for item in altered["references"]["items"]:
            if item["inclusion"] == "included":
                item["observed_sha256"] = "0" * 64
        with self.assertRaises(TransferArchiveError):
            plan_artifact_restore(replace(archive, storage=altered), roots=self.roots)

    def test_reference_cannot_be_rebound_to_another_owner_or_job(self):
        _inventory, archive = self.archive(False)
        altered = deepcopy(archive.storage)
        altered["references"]["items"][0]["key"] = "bob/delivery.zip"
        with self.assertRaises(TransferArchiveError):
            validate_reference_inventory(replace(archive, storage=altered))

    def test_reference_contract_rejects_omitted_required_and_duplicate_links(self):
        _inventory, archive = self.archive(False)
        for variant in ([], [archive.storage["references"]["items"][0]] * 2):
            altered = deepcopy(archive.storage)
            altered["references"]["items"] = variant
            with self.subTest(variant=variant), self.assertRaises(TransferArchiveError):
                validate_reference_inventory(replace(archive, storage=altered))

    def test_valid_payload_can_be_explicitly_excluded_after_validation(self):
        self.input_file()
        _inventory, archive = self.archive(True)
        stripped = without_payloads(archive)
        self.assertFalse(stripped.entries)
        self.assertFalse(stripped.directories)
        self.assertEqual(stripped.storage["references"]["mode"], "records_only")
        self.assertTrue(any(row["inclusion"] == "excluded" and row["observed_sha256"] == self.digest
                            for row in stripped.storage["references"]["items"]))
        plan_artifact_restore(stripped, roots=self.roots)

    def test_legacy_package_can_be_imported_as_records_only(self):
        self.input_file()
        inventory = collect_artifacts(self.payload, roots=self.roots)
        write_archive(self.package, {}, self.payload, inventory.sources, directories=inventory.directories, storage=inventory.storage)
        stripped = without_payloads(inspect_archive(self.package))
        self.assertFalse(stripped.entries)
        validate_reference_inventory(stripped)

    def test_additive_selection_excludes_reference_branches_together(self):
        _inventory, archive = self.archive(False)
        selected = additive_archive(archive, {"deliveries": [3], "jobs": []})
        self.assertEqual({item["resource"] for item in selected.storage["references"]["items"]}, {"deliveries"})

    def test_receipt_translates_local_keys_without_changing_origin_or_expected_evidence(self):
        _inventory, archive = self.archive(False)
        result = {"identity_map": {"deliveries": {"3": 98}, "jobs": {self.job: self.job}}}
        receipt = receipt_references(archive, result)
        incoming = archive.storage["references"]["items"][0]
        committed = receipt["items"][0]
        self.assertEqual(committed["source_key"], "98")
        self.assertEqual(committed["id"], incoming["id"])
        self.assertEqual(committed["origin"], incoming["origin"])
        self.assertEqual(committed["expected_sha256"], incoming["expected_sha256"])
        self.assertEqual(incoming["source_key"], "3")

    def test_unsafe_source_is_rejected_even_for_records_only(self):
        path = self.roots["incoming"] / "alice"
        path.symlink_to(self.roots["work"], target_is_directory=True)
        with self.assertRaises(TransferArchiveError):
            collect_artifacts(self.payload, roots=self.roots, include_files=False)

    def test_unactivated_retained_boundary_generation_is_preserved_without_activation(self):
        prefix = self.roots["boundaries"] / ".boundary-generations" / ("legacy-" + "a" * 32)
        (prefix / "raster").mkdir(parents=True)
        (prefix / "vector").mkdir()
        (prefix / "raster" / "boundary.tif").write_bytes(b"retained boundary")
        _inventory, archive = self.archive(True)
        self.assertEqual(archive.storage["boundaries"], {"mode": "retained"})
        self.assertTrue(any(item["root"] == "boundaries" for item in archive.entries))
        targets = {name: self.root / "target" / name for name in self.roots}
        plan_artifact_restore(archive, roots=targets).apply()
        self.assertFalse((targets["boundaries"] / ".boundary-current").exists())
        self.assertTrue((targets["boundaries"] / ".boundary-generations" / prefix.name / "raster" / "boundary.tif").exists())

    def test_records_only_does_not_hash_delivery_job_or_boundary_payloads(self):
        self.input_file()
        from uuid import UUID
        job_directory = self.roots["work"] / ("job_" + UUID(self.job).hex)
        job_directory.mkdir()
        (job_directory / "report.pdf").write_bytes(b"report payload")
        prefix = self.roots["boundaries"] / ".boundary-generations" / ("legacy-" + "a" * 32)
        (prefix / "raster").mkdir(parents=True)
        (prefix / "vector").mkdir()
        (prefix / "raster" / "boundary.tif").write_bytes(b"boundary payload")
        with patch("qc_tool.database.transfers.artifact_references._hash", side_effect=AssertionError("Excluded payload must not be read")):
            inventory = collect_artifacts(self.payload, roots=self.roots, include_files=False)
        inputs = [item for item in inventory.storage["references"]["items"] if item["role"] in {"delivery_input", "job_input"}]
        self.assertTrue(all(item["expected_sha256"] == self.digest and item["observed_sha256"] is None
                            and item["availability"] == "unverified" for item in inputs))
        self.assertFalse(inventory.sources)


class ArtifactReferencePersistenceTests(TestCase):
    """Use the existing real-publication fixture without production data."""

    from qc_tool.database.tests.integration import test_transfer_application as _fixture_module
    setUp = _fixture_module.ApplicationTransferIntegrationTests.setUp
    configuration = _fixture_module.ApplicationTransferIntegrationTests.configuration
    make_graph = _fixture_module.ApplicationTransferIntegrationTests.make_graph

    def roots(self):
        return {"work": self.source_config["work_dir"], "incoming": self.source_config["incoming_dir"],
                "submissions": self.source_config["submission_dir"], "boundaries": self.source_config["boundary_dir"]}

    def optional_archive(self, *, include_files=False):
        from qc_tool.database.transfers.records import export_records
        payload = export_records("application")
        inventory = collect_artifacts(payload, roots=self.roots(), include_files=include_files)
        package = self.root / (str(uuid4()) + ".zip")
        write_archive(package, {}, payload, inventory.sources, directories=inventory.directories, storage=inventory.storage)
        return inspect_archive(package)

    def persist(self, archive):
        from qc_tool.database.models import TransferReceipt
        mappings = {name: {str(row[{"jobs": "job_uuid", "submissions": "submission_uuid"}.get(name, "id")]):
                          row[{"jobs": "job_uuid", "submissions": "submission_uuid"}.get(name, "id")]
                          for row in rows} for name, rows in archive.records["records"].items()}
        result = {"identity_map": mappings}
        refs = receipt_references(archive, result)
        TransferReceipt.objects.create(package_id=uuid4(), operation_id=uuid4(), package_sha256="a" * 64,
            plan_sha256="b" * 64, profile="application", actor=self.actor, actor_name=self.actor.username,
            summary={"artifact_references": refs})
        return refs

    def test_complete_published_history_is_valid_without_artifact_payloads(self):
        archive = self.optional_archive()
        self.assertFalse(archive.entries)
        plan_artifact_restore(archive, roots=self.roots())
        roles = {item["role"] for item in archive.storage["references"]["items"]}
        self.assertTrue({"publication_manifest", "publication_file", "specification", "job_input"} <= roles)

    def test_records_only_publication_reads_only_bounded_original_metadata(self):
        from qc_tool.database.transfers import artifact_references
        original_hash = artifact_references._hash
        def bounded_metadata_hash(stream, maximum, *args):
            self.assertLessEqual(maximum, 1024**2, "Records-only must not hash bulk artifact bytes")
            return original_hash(stream, maximum, *args)
        with patch.object(artifact_references, "_hash", side_effect=bounded_metadata_hash):
            archive = self.optional_archive()
        expected_inputs = [item for item in archive.storage["references"]["items"] if item["role"] in {"delivery_input", "job_input"}]
        self.assertTrue(all(item["expected_sha256"] == self.input_digest and item["observed_sha256"] is None for item in expected_inputs))
        publication_files = [item for item in archive.storage["references"]["items"] if item["role"] == "publication_file"]
        self.assertTrue(publication_files)
        self.assertTrue(all(item["expected_sha256"] is not None and item["observed_sha256"] is None for item in publication_files))

    def test_partial_source_publication_keeps_missing_references(self):
        (self.source_config["submission_dir"] / self.submission.artifact_key / "report.pdf").unlink()
        archive = self.optional_archive(include_files=True)
        plan_artifact_restore(archive, roots={name: self.root / "empty" / name for name in self.roots()})
        missing = [item for item in archive.storage["references"]["items"] if item["availability"] == "missing"]
        self.assertTrue(any(item["role"] == "publication_file" and item["key"].endswith("/report.pdf") for item in missing))

    def test_missing_original_manifest_and_files_do_not_drop_retained_inventory_on_reexport(self):
        archive = self.optional_archive()
        refs = self.persist(archive)
        publication = self.source_config["submission_dir"] / self.submission.artifact_key
        (publication / "submission-manifest.json").unlink()
        (self.source_config["incoming_dir"] / self.owner.username / "fixture.zip").unlink()
        reexported = self.optional_archive()
        restored = {item["id"]: item for item in reexported.storage["references"]["items"]}
        for item in refs["items"]:
            self.assertIn(item["id"], restored)
            if item["expected_sha256"] is not None or item["role"] in {"delivery_input", "job_input", "specification"}:
                self.assertEqual(restored[item["id"]]["expected_sha256"], item["expected_sha256"])
            self.assertEqual(restored[item["id"]]["observed_sha256"], item["observed_sha256"])

    def test_imported_hashless_delivery_cannot_use_unchecked_legacy_download(self):
        from qc_tool.frontend.dashboard.services.artifacts import ArtifactUnavailable
        from qc_tool.frontend.dashboard.services.artifacts.inputs import open_delivery_input
        delivery = self.submission.delivery
        delivery.content_sha256 = None
        delivery.save(update_fields=["content_sha256"])
        self.persist(self.optional_archive())
        with self.assertRaises(ArtifactUnavailable):
            open_delivery_input(delivery)

    def test_previous_report_identity_is_retained_when_current_bytes_change(self):
        archive = self.optional_archive(include_files=True)
        self.persist(archive)
        from uuid import UUID
        report = self.source_config["work_dir"] / ("job_" + UUID(str(self.submission.job_id)).hex) / "report.pdf"
        old = hashlib.sha256(report.read_bytes()).hexdigest()
        report.write_bytes(b"different replacement report")
        reexported = self.optional_archive(include_files=True)
        reference = next(item for item in reexported.storage["references"]["items"]
                         if item["role"] == "job_output" and item["key"].endswith("/report.pdf"))
        self.assertEqual(reference["expected_sha256"], old)
        self.assertEqual(reference["availability"], "different")
        self.assertEqual(reference["inclusion"], "unavailable")
        self.assertNotIn((reference["root"], reference["key"]), {(item["root"], item["key"]) for item in reexported.entries})

    def test_committed_artifact_identity_cannot_be_rebound_to_another_record(self):
        archive = self.optional_archive()
        self.persist(archive)
        mappings = {name: {str(row[{"jobs": "job_uuid", "submissions": "submission_uuid"}.get(name, "id")]):
                          row[{"jobs": "job_uuid", "submissions": "submission_uuid"}.get(name, "id")]
                          for row in rows} for name, rows in archive.records["records"].items()}
        mappings["deliveries"][str(self.submission.delivery_id)] = self.submission.delivery_id + 1000
        with self.assertRaisesMessage(TransferArchiveError, "already bound"):
            receipt_references(archive, {"identity_map": mappings})

    def test_partial_publication_payload_reuses_additional_exact_retained_target_files(self):
        targets = {name: self.root / "retained-target" / name for name in self.roots()}
        for name, directory in self.roots().items():
            shutil.copytree(directory, targets[name])
        (self.source_config["submission_dir"] / self.submission.artifact_key / "report.pdf").unlink()
        archive = self.optional_archive(include_files=True)
        self.assertEqual(inspect_retained_artifact_conflicts(archive, roots=targets), [])
        plan_artifact_restore(archive, roots=targets)
        report = targets["submissions"] / self.submission.artifact_key / "report.pdf"
        report.write_bytes(b"wrong retained report")
        self.assertTrue(inspect_retained_artifact_conflicts(archive, roots=targets))
        with self.assertRaises(TransferArchiveError):
            plan_artifact_restore(archive, roots=targets)
