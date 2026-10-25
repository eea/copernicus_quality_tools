"""Selected deployment secrets stay in private payloads and never activate."""

import base64
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from qc_tool.database.transfers import configuration
from qc_tool.database.transfers.archive import ArtifactSource, inspect_archive, write_archive
from qc_tool.database.transfers.errors import TransferError


class ConfigurationBackupTests(SimpleTestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.credentials = self.root / "credentials"
        self.work = self.root / "work"
        self.boundaries = self.root / "boundaries"
        self.enterContext(patch.dict(configuration.CONFIG, work_dir=self.work, boundary_dir=self.boundaries))
        self.credentials.mkdir(mode=0o700)
        self.enterContext(override_settings(S3_CREDENTIALS_DIR=self.credentials,
                                          SECRET_KEY="private-application-key"))
        self.name = "a" * 32 + ".json"
        self.raw = b'{"access_key":"original-access","secret_key":"original-secret"}\n'
        self.path = self.credentials / self.name
        self.path.write_bytes(self.raw)
        self.path.chmod(0o600)

    def package(self, snapshot, *, omit=()):
        sources = []
        for index, (key, raw) in enumerate(snapshot.sections.items()):
            if key in omit:
                continue
            path = self.root / ("section-" + str(index))
            path.write_bytes(raw)
            sources.append(ArtifactSource("database", key, path))
        path = self.root / "package.zip"
        write_archive(path, {}, {}, sources)
        return inspect_archive(path)

    def test_snapshot_preserves_original_secret_bytes_and_runtime_key(self):
        snapshot = configuration.snapshot()
        self.assertEqual(snapshot.sections["credentials/s3/" + self.name], self.raw)
        document = json.loads(snapshot.sections["metadata/deployment.json"])
        self.assertEqual(document["settings"]["SECRET_KEY"], "private-application-key")
        self.assertEqual(document["restore"], "operator_review_only")
        self.assertEqual(snapshot.files_count, 2)
        self.assertNotIn("original-secret", repr(snapshot))
        self.assertNotIn("private-application-key", repr(snapshot))
        configuration.validate(self.package(snapshot))

    def test_absent_credential_store_is_explicit_and_never_created(self):
        absent = self.root / "absent"
        with override_settings(S3_CREDENTIALS_DIR=absent):
            snapshot = configuration.snapshot()
        document = json.loads(snapshot.sections["metadata/deployment.json"])
        self.assertEqual(document["credential_store"], {"state": "absent", "files": []})
        self.assertFalse(absent.exists())

    def test_changed_secret_invalidates_review_fingerprint(self):
        before = configuration.snapshot()
        self.path.write_bytes(self.raw.replace(b"original-secret", b"modified-secret"))
        self.assertNotEqual(configuration.snapshot().fingerprint, before.fingerprint)

    def test_nonprivate_linked_or_oversized_credentials_are_refused(self):
        self.path.chmod(0o644)
        with self.assertRaises(TransferError):
            configuration.snapshot()
        self.path.chmod(0o600)
        self.path.write_bytes(b"x" * 8193)
        with self.assertRaises(TransferError):
            configuration.snapshot()
        self.path.unlink()
        self.path.symlink_to(self.root / "other-secret")
        with self.assertRaises(TransferError):
            configuration.snapshot()

    def test_package_must_contain_exact_declared_credentials(self):
        snapshot = configuration.snapshot()
        with self.assertRaisesMessage(TransferError, "disagree"):
            configuration.validate(self.package(snapshot, omit=["credentials/s3/" + self.name]))

    def test_selected_configuration_is_bounded(self):
        with patch.object(configuration, "MAX_BYTES", 8):
            with self.assertRaisesMessage(TransferError, "limit"):
                configuration.snapshot()

    def test_worker_and_referenced_postgresql_tls_files_are_preserved_inertly(self):
        from unittest.mock import patch
        from django.db import connection
        from qc_tool.common import CONFIG

        work = self.root / "work"
        work.mkdir()
        token = work / "worker.token"
        token.write_bytes(b"original-worker-token")
        token.chmod(0o600)
        key = self.root / "postgres-client.key"
        key.write_bytes(b"original-client-key")
        key.chmod(0o600)
        options = {"sslkey": str(key), "sslmode": "verify-full"}
        with patch.dict(CONFIG, work_dir=work), patch.dict(connection.settings_dict, OPTIONS=options):
            snapshot = configuration.snapshot()
        self.assertEqual(snapshot.sections["credentials/worker.token"], b"original-worker-token")
        self.assertEqual(snapshot.sections["credentials/postgresql/sslkey"], b"original-client-key")
        self.assertEqual(json.loads(snapshot.sections["metadata/deployment.json"])["database"]["OPTIONS"], options)
        configuration.validate(self.package(snapshot))
        self.assertEqual(token.read_bytes(), b"original-worker-token")

    def test_activation_state_preserves_original_bytes_without_rewriting_or_applying_them(self):
        states = self.work / "product_definitions" / ".state"
        states.mkdir(parents=True)
        original = b'{ "active" : true, "digest" : "original value" }\n'
        state = states / "example.json"
        state.write_bytes(original)
        before = state.stat()
        snapshot = configuration.snapshot()
        document = json.loads(snapshot.sections["metadata/deployment.json"])
        self.assertEqual(document["activation"]["specifications"], {"state": "included", "files": [{
            "key": "example.json", "sha256": hashlib.sha256(original).hexdigest(), "size": len(original),
            "content_base64": base64.b64encode(original).decode("ascii")} ]})
        self.assertEqual(document["activation"]["boundaries"], {"state": "absent", "entries": {}})
        self.assertEqual(state.read_bytes(), original)
        self.assertEqual(state.stat().st_ino, before.st_ino)
        self.assertFalse((self.boundaries / ".boundary-current").exists())
        configuration.validate(self.package(snapshot))

    def test_boundary_link_targets_are_preserved_without_resolving_even_dangling_links(self):
        self.boundaries.mkdir()
        generation = ".boundary-generations/gen-" + "a" * 32
        (self.boundaries / ".boundary-current").symlink_to(generation)
        for name in ("raster", "vector"):
            (self.boundaries / name).symlink_to(".boundary-current/" + name)
        snapshot = configuration.snapshot()
        document = json.loads(snapshot.sections["metadata/deployment.json"])
        entries = document["activation"]["boundaries"]["entries"]
        self.assertEqual(entries[".boundary-current"], {"state": "link", "target": generation})
        self.assertEqual(entries["raster"], {"state": "link", "target": ".boundary-current/raster"})
        self.assertFalse((self.boundaries / generation).exists())
        self.assertEqual(os.readlink(self.boundaries / ".boundary-current"), generation)
        configuration.validate(self.package(snapshot))

    def test_legacy_boundary_directories_and_absent_activation_states_are_explicit(self):
        self.boundaries.mkdir()
        (self.boundaries / "raster").mkdir()
        document = json.loads(configuration.snapshot().sections["metadata/deployment.json"])
        self.assertEqual(document["activation"], {
            "boundaries": {"state": "included", "entries": {
                ".boundary-current": {"state": "absent"}, "raster": {"state": "directory"}, "vector": {"state": "absent"}}},
            "specifications": {"state": "absent", "files": []}})

    def test_arbitrary_boundary_links_and_parent_or_file_symlinks_are_refused(self):
        self.boundaries.mkdir()
        pointer = self.boundaries / ".boundary-current"
        for target in (str(self.root / "private"), "../private", ".boundary-generations/../../private"):
            pointer.symlink_to(target)
            with self.subTest(target=target), self.assertRaisesMessage(TransferError, "unsafe target"):
                configuration.snapshot()
            pointer.unlink()
        definitions = self.work / "product_definitions"
        definitions.mkdir(parents=True)
        outside = self.root / "outside-state"
        outside.mkdir()
        (definitions / ".state").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(TransferError):
            configuration.snapshot()
        (definitions / ".state").unlink()
        (definitions / ".state").mkdir()
        (definitions / ".state" / "example.json").symlink_to(self.path)
        with self.assertRaisesMessage(TransferError, "regular files"):
            configuration.snapshot()

    def test_activation_file_size_and_inventory_are_strictly_bounded(self):
        states = self.work / "product_definitions" / ".state"
        states.mkdir(parents=True)
        (states / "example.json").write_bytes(b"12345")
        with patch.object(configuration, "MAX_ACTIVATION_FILE_BYTES", 4), self.assertRaisesMessage(TransferError, "supported size"):
            configuration.snapshot()
        with patch.object(configuration, "MAX_FILES", 0), self.assertRaises(TransferError):
            configuration._activation_snapshot()

    def test_changed_boundary_activation_link_is_refused_during_capture(self):
        self.boundaries.mkdir()
        pointer = self.boundaries / ".boundary-current"
        pointer.symlink_to(".boundary-generations/gen-" + "a" * 32)
        original_readlink = os.readlink

        def changed(name, **kwargs):
            target = original_readlink(name, **kwargs)
            pointer.unlink()
            pointer.symlink_to(".boundary-generations/gen-" + "b" * 32)
            return target

        with patch.object(configuration.os, "readlink", side_effect=changed), self.assertRaisesMessage(TransferError, "changed"):
            configuration.snapshot()

    def test_inbound_activation_metadata_rejects_traversal_corrupt_bytes_and_oversize(self):
        document = json.loads(configuration.snapshot().sections["metadata/deployment.json"])
        activation = document["activation"]
        activation["boundaries"] = {"state": "included", "entries": {
            name: {"state": "absent"} for name in (".boundary-current", "raster", "vector")}}
        activation["boundaries"]["entries"]["raster"] = {"state": "link", "target": "../../private"}
        with self.assertRaisesMessage(TransferError, "unsafe"):
            configuration._validate_activation(activation)
        activation["boundaries"]["entries"]["raster"] = {"state": "absent"}
        activation["specifications"] = {"state": "included", "files": [{
            "key": "../example.json", "sha256": "a" * 64, "size": 1, "content_base64": "eA=="}]}
        with self.assertRaises(TransferError):
            configuration._validate_activation(activation)
        entry = activation["specifications"]["files"][0]
        entry["key"] = "example.json"
        with self.assertRaisesMessage(TransferError, "disagree"):
            configuration._validate_activation(activation)
        entry["size"] = configuration.MAX_ACTIVATION_FILE_BYTES + 1
        with self.assertRaisesMessage(TransferError, "invalid"):
            configuration._validate_activation(activation)
