"""Stable archive identities retain exact bytes across separated storage mounts."""

import base64
import hashlib
import json
from pathlib import Path
import shutil
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings

from qc_tool.common import CONFIG
from qc_tool.database.tests.integration import test_transfer_application as _application_fixture
from qc_tool.database.tests.integration import test_transfer_recovery_files as _recovery_fixture
from qc_tool.database.tests.integration import test_transfer_configuration as _configuration_fixture
from qc_tool.database.transfers import configuration, recovery_files, service
from qc_tool.database.transfers.archive import inspect_archive, write_archive
from qc_tool.database.transfers.artifact_references import validate_reference_inventory
from qc_tool.database.transfers.artifacts import collect_artifacts, plan_artifact_restore, storage_roots
from qc_tool.database.transfers.records import export_records
from qc_tool.frontend.dashboard.services.catalog.manifest.definitions import parse_definition_snapshot
from qc_tool.storage.layout import runtime_paths


class SeparatedRecoveryFileTests(SimpleTestCase):
    setUp = _recovery_fixture.RecoveryFileTests.setUp
    package = _recovery_fixture.RecoveryFileTests.package

    def add_specifications(self):
        self.roots["specifications"] = self.root / "dedicated-specifications"
        self.roots["specifications"].mkdir()
        self.original = b'{\n  "description": "Original byte formatting", "steps": []\n}\n\n'
        self.digest = hashlib.sha256(self.original).hexdigest()
        version = self.roots["specifications"] / ".versions" / "example" / (self.digest + ".json")
        version.parent.mkdir(parents=True)
        version.write_bytes(self.original)
        states = self.roots["specifications"] / ".state"
        states.mkdir()
        self.activation = b'{ "active" : true, "digest" : "' + self.digest.encode() + b'" }\n'
        (states / "example.json").write_bytes(self.activation)
        return version

    def test_native_inventory_and_idempotent_restore_keep_logical_keys_and_separate_physical_bytes(self):
        version = self.add_specifications()
        original_inode = version.stat().st_ino
        archive = self.package()
        expected_key = "product_definitions/.versions/example/" + self.digest + ".json"
        entry = next(item for item in archive.entries if item["key"] == expected_key)
        self.assertEqual(entry["root"], "work")
        self.assertFalse(any(item["root"] == "specifications" for item in archive.entries))
        self.assertFalse(any("/.state/" in item["key"] for item in archive.entries))
        targets = {key: self.root / "target" / key for key in self.roots}
        journal = self.root / "restore-files.json"
        recovery_files.plan_restore(archive, roots=targets, journal_path=journal).apply()
        # Reload the real publication journal, verifying translated paths on recovery.
        recovery_files.plan_restore(archive, roots=targets, journal_path=journal).apply()
        self.assertEqual((targets["specifications"] / ".versions/example" / (self.digest + ".json")).read_bytes(), self.original)
        self.assertFalse((targets["specifications"] / ".state").exists())
        self.assertFalse((targets["work"] / "product_definitions").exists())
        self.assertEqual((targets["incoming"] / "old-owner/old.zip").read_bytes(), b"historical unlinked ZIP")
        self.assertEqual((targets["work"] / ("job_" + "a" * 32) / "report.html").read_bytes(), b"original report")
        self.assertEqual(version.stat().st_ino, original_inode)
        self.assertEqual(version.read_bytes(), self.original)
        self.assertEqual((self.roots["specifications"] / ".state/example.json").read_bytes(), self.activation)

    def test_optional_specification_reference_roundtrip_restores_exact_bytes_without_activation(self):
        self.add_specifications()
        parsed = parse_definition_snapshot("example", self.original, source_path="upload:example.json")
        payload = {"profile": "application", "accounts": [], "records": {"definitions": [{
            "id": 1, "product_ident": "example", "digest": parsed.digest, "document": parsed.document,
            "source_path": parsed.source_path,
        }]}}
        inventory = collect_artifacts(payload, roots=self.roots, include_files=True)
        source = next(item for item in inventory.sources if item.key.startswith("product_definitions/"))
        self.assertEqual(source.storage_root, self.roots["specifications"])
        self.assertEqual(source.root, "work")
        package = self.root / "optional.zip"
        write_archive(package, {}, payload, inventory.sources, directories=inventory.directories, storage=inventory.storage)
        archive = inspect_archive(package)
        references = validate_reference_inventory(archive)
        reference = next(item for item in references["items"] if item["role"] == "specification")
        self.assertEqual((reference["root"], reference["availability"], reference["inclusion"]), ("work", "verified", "included"))
        targets = {key: self.root / "optional-target" / key for key in self.roots}
        plan_artifact_restore(archive, roots=targets, journal_path=self.root / "optional-files.json").apply()
        target = targets["specifications"] / ".versions/example" / (self.digest + ".json")
        self.assertEqual(target.read_bytes(), self.original)
        self.assertFalse((targets["work"] / "product_definitions").exists())
        self.assertFalse((targets["specifications"] / ".state").exists())
        # Byte conflicts at the actual dedicated destination are refused, never
        # diverted into a same-named job-side specification directory.
        target.write_bytes(b"different original bytes")
        with self.assertRaises(ValueError):
            plan_artifact_restore(archive, roots=targets)
        self.assertEqual(target.read_bytes(), b"different original bytes")
        self.assertFalse((targets["work"] / "product_definitions").exists())

    def test_deployment_activation_and_worker_token_use_their_owning_mounts(self):
        version = self.add_specifications()
        shared = self.root / "shared-state"
        shared.mkdir()
        token = shared / "worker.token"
        token.write_bytes(b"private-worker-token-fixture")
        token.chmod(0o600)
        with patch.dict(CONFIG, data_root=self.root, work_dir=self.roots["work"],
                        incoming_dir=self.roots["incoming"], boundary_dir=self.roots["boundaries"],
                        product_dirs=[], specifications_dir=self.roots["specifications"], shared_state_dir=shared), \
                override_settings(S3_CREDENTIALS_DIR=self.root / "absent-credentials"):
            snapshot = configuration.snapshot()
            paths = runtime_paths(CONFIG)
        document = json.loads(snapshot.sections["metadata/deployment.json"])
        self.assertEqual(document["version"], 2)
        self.assertEqual(document["storage"]["specifications_dir"], str(self.roots["specifications"]))
        self.assertEqual(document["storage"]["shared_state_dir"], str(shared))
        for key, value in (("data_root", paths.data_root), ("frontend_state_dir", paths.frontend_state_dir),
                           ("scratch_dir", paths.scratch_dir), ("log_dir", paths.logs_dir),
                           ("transfer_dir", paths.transfer_dir), ("backups_dir", paths.backups_dir),
                           ("upload_temp_dir", paths.upload_temp_dir), ("static_dir", paths.static_dir)):
            self.assertEqual(document["storage"][key], str(value) if value is not None else None)
        activation = document["activation"]["specifications"]
        self.assertEqual(activation["state"], "included")
        self.assertEqual(base64.b64decode(activation["files"][0]["content_base64"]), self.activation)
        self.assertEqual(snapshot.sections["credentials/worker.token"], b"private-worker-token-fixture")
        self.assertEqual(version.read_bytes(), self.original)
        self.assertFalse((self.roots["work"] / "worker.token").exists())
        self.assertFalse((self.roots["work"] / "product_definitions").exists())
        configuration.validate(_configuration_fixture.ConfigurationBackupTests.package(self, snapshot))

    def test_legacy_deployment_metadata_keeps_version_one_reader_and_exact_old_storage_keys(self):
        with patch.dict(CONFIG, data_root=None, specifications_dir=None,
                        work_dir=self.roots["work"], boundary_dir=self.roots["boundaries"]), \
                override_settings(S3_CREDENTIALS_DIR=self.root / "absent-legacy-credentials"):
            snapshot = configuration.snapshot()
        document = json.loads(snapshot.sections["metadata/deployment.json"])
        self.assertEqual(document["version"], 1)
        self.assertEqual(set(document["storage"]), {
            "work_dir", "incoming_dir", "boundary_dir", "product_dirs", "submission_dir",
        })
        configuration.validate(_configuration_fixture.ConfigurationBackupTests.package(self, snapshot))

    def test_explicit_separated_specification_override_is_used_without_canonical_data_root(self):
        self.add_specifications()
        with patch.dict(CONFIG, data_root=None, specifications_dir=self.roots["specifications"],
                        work_dir=self.roots["work"], incoming_dir=self.roots["incoming"],
                        boundary_dir=self.roots["boundaries"], submission_dir=self.roots["submissions"],
                        product_dirs=[]):
            roots = storage_roots()
        self.assertEqual(roots.get("specifications"), self.roots["specifications"])
        inventory = recovery_files.collect(roots=roots, components=["specifications"])
        self.assertEqual([source.path.read_bytes() for source in inventory.sources], [self.original])

    def test_old_job_side_specification_directory_cannot_duplicate_or_override_selected_mount(self):
        self.add_specifications()
        shadow = self.roots["work"] / "product_definitions"
        shadow.mkdir()
        (shadow / "shadow.json").write_bytes(b"unselected legacy bytes")
        inventory = recovery_files.collect(roots=self.roots, components=["specifications"])
        self.assertEqual(len(inventory.sources), 1)
        self.assertEqual(inventory.sources[0].path.read_bytes(), self.original)
        self.assertEqual((shadow / "shadow.json").read_bytes(), b"unselected legacy bytes")


class SeparatedApplicationTransferTests(TestCase):
    setUp = _application_fixture.ApplicationTransferIntegrationTests.setUp
    prepare_import = _application_fixture.ApplicationTransferIntegrationTests.prepare_import
    assert_restored = _application_fixture.ApplicationTransferIntegrationTests.assert_restored

    def configuration(self, prefix):
        base = self.root / prefix
        data = base / "data"
        config = {"data_root": data, "work_dir": data / "jobs", "incoming_dir": data / "incoming",
                  "submission_dir": data / "submissions", "boundary_dir": data / "boundaries",
                  "specifications_dir": data / "specifications", "shared_state_dir": base / "shared",
                  "frontend_state_dir": base / "frontend", "scratch_dir": base / "scratch",
                  "log_dir": base / "logs", "product_dirs": []}
        for key, value in config.items():
            if key != "product_dirs":
                value.mkdir(parents=True, exist_ok=True)
        return config

    def make_graph(self):
        # Reuse the existing real SQL/publication fixture, then place its original
        # specification bytes on the canonical mount before any transfer starts.
        _application_fixture.ApplicationTransferIntegrationTests.make_graph(self)
        old = self.source_config["work_dir"] / "product_definitions"
        shutil.copytree(old, self.source_config["specifications_dir"], dirs_exist_ok=True)
        shutil.rmtree(old)  # disposable fixture only

    def test_full_application_roundtrip_preserves_connected_publication_and_separate_specification(self):
        roots = storage_roots()
        self.assertEqual(roots["specifications"], self.source_config["specifications_dir"])
        inventory = collect_artifacts(export_records("application"), include_files=True)
        originals = [item for item in inventory.sources if item.key.startswith("product_definitions/")]
        self.assertTrue(originals)
        self.assertTrue(all(item.storage_root == self.source_config["specifications_dir"] for item in originals))
        operation = self.prepare_import()
        self.assertEqual(service.run_operation(operation["id"])["status"], "completed")
        self.assert_restored()
        versions = list(self.target_config["specifications_dir"].glob(".versions/transfer-product/*.json"))
        self.assertEqual([path.read_bytes() for path in versions], [self.specification])
        for config in (self.source_config, self.target_config):
            self.assertFalse((config["work_dir"] / "product_definitions").exists())
        self.assertFalse((self.target_config["specifications_dir"] / ".state").exists())
