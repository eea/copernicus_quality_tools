"""Untrusted package and immutable-storage regression tests (temporary files only)."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from unittest.mock import patch
from uuid import uuid4
import zipfile

from django.test import SimpleTestCase

from qc_tool.database.transfers.archive import (
    ArchiveLimits, ArtifactSource, TransferArchiveError, canonical_json,
    inspect_archive, open_regular, validate_key, write_archive,
)
from qc_tool.database.transfers.artifacts import (
    additive_archive, collect_artifacts, inspect_delivery_files,
    inspect_retained_artifact_conflicts, plan_artifact_restore,
)


class TransferArchiveTests(SimpleTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.package = self.root / "transfer.zip"
        self.source = self.root / "source.bin"
        self.source.write_bytes(b"original bytes\x00\xff")

    def write(self, **options):
        return write_archive(self.package, {"description": "test"}, {"profile": "accounts"}, **options)

    def rewrite(self, transform):
        with zipfile.ZipFile(self.package) as package:
            contents = {item.filename: package.read(item.filename) for item in package.infolist()}
        transform(contents)
        with zipfile.ZipFile(self.package, "w") as package:
            for name, payload in contents.items():
                package.writestr(name, payload)

    def test_roundtrip_canonical_records_and_original_artifact_bytes(self):
        sha = self.write(artifacts=[ArtifactSource("incoming", "alice/input.zip", self.source)])
        verified = inspect_archive(self.package)
        self.assertEqual(verified.package_sha256, sha)
        self.assertEqual(verified.manifest, {"description": "test"})
        self.assertEqual(verified.records, {"profile": "accounts"})
        output = self.root / "copied"
        with output.open("wb") as stream:
            verified.copy_artifact(verified.entries[0], stream)
        self.assertEqual(output.read_bytes(), self.source.read_bytes())
        self.assertEqual(stat.S_IMODE(self.package.stat().st_mode), 0o600)

    def test_never_overwrites_an_existing_package(self):
        self.package.write_bytes(b"keep")
        with self.assertRaises(TransferArchiveError):
            self.write()
        self.assertEqual(self.package.read_bytes(), b"keep")

    def test_rejects_traversal_control_unicode_and_windows_paths(self):
        for value in ("../x", "/x", "a/../b", "a//b", "a/./b", "a\\b", "c:thing", "a\x00b", "a\u200bb", "e\u0301", "a/" ):
            with self.subTest(value=value), self.assertRaises(TransferArchiveError):
                validate_key(value)

    def test_rejects_unlisted_files_and_case_collisions(self):
        for name in ("extra.txt", "RECORDS.JSON", "../escaped"):
            self.package.unlink(missing_ok=True)
            self.write()
            self.rewrite(lambda contents: contents.update({name: b"x"}))
            with self.subTest(name=name), self.assertRaises(TransferArchiveError):
                inspect_archive(self.package)
        self.assertFalse((self.root.parent / "escaped").exists())

    def test_rejects_duplicate_zip_members(self):
        self.write()
        with zipfile.ZipFile(self.package, "a") as package:
            with self.assertWarns(UserWarning):
                package.writestr("records.json", b"{}")
        with self.assertRaises(TransferArchiveError):
            inspect_archive(self.package)

    def test_rejects_symlink_and_special_members(self):
        for kind in (stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR, stat.S_IFSOCK):
            with zipfile.ZipFile(self.package, "w") as package:
                info = zipfile.ZipInfo("bad")
                info.external_attr = (kind | 0o600) << 16
                package.writestr(info, b"target")
            with self.subTest(kind=kind), self.assertRaises(TransferArchiveError):
                inspect_archive(self.package)

    def test_rejects_changed_records_checksum_unknown_version_and_duplicate_json(self):
        transforms = [
            lambda files: files.update({"records.json": b'{"changed":true}'}),
            lambda files: files.update({"manifest.json": files["manifest.json"].replace(b'"version":1', b'"version":99')}),
            lambda files: files.update({"manifest.json": b'{"archive":{},"archive":{}}'}),
        ]
        for transform in transforms:
            self.package.unlink(missing_ok=True)
            self.write()
            self.rewrite(transform)
            with self.assertRaises(TransferArchiveError):
                inspect_archive(self.package)

    def test_rejects_changed_artifact_hash_and_truncated_zip(self):
        self.write(artifacts=[ArtifactSource("incoming", "a.zip", self.source)])
        self.rewrite(lambda files: files.update({"artifacts/incoming/a.zip": b"wrong"}))
        with self.assertRaises(TransferArchiveError):
            inspect_archive(self.package)
        self.package.write_bytes(self.package.read_bytes()[:-10])
        with self.assertRaises(TransferArchiveError):
            inspect_archive(self.package)

    def test_enforces_compressed_uncompressed_metadata_and_entry_limits(self):
        self.write()
        variants = [ArchiveLimits(max_archive_bytes=10), ArchiveLimits(max_manifest_bytes=10),
                    ArchiveLimits(max_records_bytes=10), ArchiveLimits(max_members=1),
                    ArchiveLimits(max_total_bytes=10), ArchiveLimits(max_central_directory_bytes=10)]
        for limits in variants:
            with self.subTest(limits=limits), self.assertRaises(TransferArchiveError):
                inspect_archive(self.package, limits=limits)
        with zipfile.ZipFile(self.package, "w", compression=zipfile.ZIP_DEFLATED) as package:
            package.writestr("huge", b"A" * 100_000)
        with self.assertRaises(TransferArchiveError):
            inspect_archive(self.package, limits=ArchiveLimits(max_compression_ratio=2))

    def test_source_symlinks_and_parent_symlinks_are_rejected(self):
        link = self.root / "linked.bin"
        link.symlink_to(self.source)
        with self.assertRaises(TransferArchiveError):
            self.write(artifacts=[ArtifactSource("incoming", "a.zip", link)])
        real = self.root / "real"
        real.mkdir()
        (real / "file").write_bytes(b"x")
        (self.root / "linked-dir").symlink_to(real, target_is_directory=True)
        with self.assertRaises(TransferArchiveError), open_regular(self.root / "linked-dir" / "file", storage_root=self.root):
            pass

    def test_nonfinite_json_is_rejected(self):
        with self.assertRaises(TransferArchiveError):
            canonical_json({"nan": float("nan")})


class TransferArtifactTests(SimpleTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source_roots = {name: self.root / "source" / name for name in ("work", "incoming", "submissions", "boundaries")}
        self.target_roots = {name: self.root / "target" / name for name in self.source_roots}
        for path in self.source_roots.values():
            path.mkdir(parents=True)
        self.payload = {"profile": "application", "accounts": [{"key": "1", "username": "alice"}], "records": {}}
        self.package = self.root / "transfer.zip"
        self.journal = self.root / "files.json"

    def journal_state(self):
        rows = [json.loads(line) for line in self.journal.read_bytes().splitlines()]
        result = {**rows[0], "files": [], "links": [], "directories": []}
        for event in rows[1:]:
            for name, count in zip(("files", "links", "directories"), event.get("counts", ())):
                del result[name][count:]
            for name in ("files", "links", "directories"):
                result[name].extend(event.get(name, []))
        return result

    def inventory_archive(self):
        inventory = collect_artifacts(self.payload, roots=self.source_roots)
        write_archive(self.package, {}, self.payload, inventory.sources, directories=inventory.directories, storage=inventory.storage)
        return inventory, inspect_archive(self.package)

    def add_delivery(self, *, deleted=False):
        content = b"ZIP original bytes"
        path = self.source_roots["incoming"] / "alice" / "input.zip"
        path.parent.mkdir()
        path.write_bytes(content)
        row = {"id": 2, "user_id": 1, "filename": "input.zip", "size_bytes": len(content),
               "content_sha256": hashlib.sha256(content).hexdigest(), "s3_id": None, "is_deleted": deleted}
        self.payload["records"]["deliveries"] = [row]
        return path, row

    def test_create_only_restore_exact_reuse_and_owned_rollback(self):
        source, _ = self.add_delivery()
        _inventory, archive = self.inventory_archive()
        plan = plan_artifact_restore(archive, roots=self.target_roots, journal_path=self.journal)
        self.assertEqual(plan.summary["create_files"], 1)
        plan.apply()
        target = self.target_roots["incoming"] / "alice" / "input.zip"
        self.assertEqual(target.read_bytes(), source.read_bytes())
        fresh = plan_artifact_restore(archive, roots=self.target_roots)
        self.assertEqual(fresh.summary["reuse_files"], 1)
        fresh.apply()
        fresh.rollback()
        self.assertTrue(target.exists())
        plan.rollback()
        self.assertFalse(target.exists())

    def test_conflicting_existing_file_and_parent_symlink_fail_before_writes(self):
        self.add_delivery()
        _, archive = self.inventory_archive()
        target = self.target_roots["incoming"] / "alice" / "input.zip"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"never overwrite")
        with self.assertRaises(TransferArchiveError):
            plan_artifact_restore(archive, roots=self.target_roots)
        self.assertEqual(target.read_bytes(), b"never overwrite")
        target.unlink()
        target.parent.rmdir()
        target.parent.symlink_to(self.source_roots["incoming"] / "alice", target_is_directory=True)
        with self.assertRaises(TransferArchiveError):
            plan_artifact_restore(archive, roots=self.target_roots)

    def test_delivery_inspection_explains_exact_retained_zip_reuse(self):
        source, row = self.add_delivery()
        self.payload["records"]["jobs"] = [{"job_uuid": str(uuid4()), "delivery_id": row["id"], "input_sha256": row["content_sha256"]}]
        _, archive = self.inventory_archive()
        target = self.target_roots["incoming"] / "alice" / "input.zip"
        target.parent.mkdir(parents=True)
        target.write_bytes(source.read_bytes())
        previous = target.stat()
        result = inspect_delivery_files(archive, roots=self.target_roots)
        self.assertEqual(result["conflicts"], [])
        self.assertEqual(result["files"][0]["status"], "retained_verified")
        self.assertEqual(result["files"][0]["job_count"], 1)
        self.assertEqual(target.stat().st_ino, previous.st_ino)
        self.assertEqual(target.read_bytes(), source.read_bytes())

    def test_delivery_inspection_proposes_skip_for_same_size_different_bytes(self):
        source, row = self.add_delivery()
        _, archive = self.inventory_archive()
        target = self.target_roots["incoming"] / "alice" / "input.zip"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"x" * len(source.read_bytes()))
        result = inspect_delivery_files(archive, roots=self.target_roots)
        self.assertEqual(result["files"][0]["status"], "different")
        self.assertEqual(result["conflicts"][0]["key"], "deliveries:" + str(row["id"]))
        self.assertEqual(result["conflicts"][0]["choices"], ["skip"])
        self.assertEqual(target.read_bytes(), b"x" * len(source.read_bytes()))

    def test_delivery_inspection_preserves_historical_checksum_gap(self):
        _source, row = self.add_delivery()
        self.payload["records"]["jobs"] = [{"job_uuid": str(uuid4()), "delivery_id": row["id"], "input_sha256": ""}]
        _, archive = self.inventory_archive()
        result = inspect_delivery_files(archive, roots=self.target_roots)
        item = result["files"][0]
        self.assertEqual(item["status"], "unverified_history")
        self.assertEqual(item["file_status"], "packaged")
        self.assertIn("no recorded input checksum", item["message"])

    def test_retained_job_logs_and_scratch_are_preserved_on_matching_reuse(self):
        identifier = str(uuid4())
        self.payload["records"]["jobs"] = [{"job_uuid": identifier}]
        key = "job_" + identifier.replace("-", "")
        source = self.source_roots["work"] / key
        source.mkdir()
        (source / "result.json").write_text('{"steps":[]}')
        (source / "output.d").mkdir()
        (source / "output.d" / "report.txt").write_bytes(b"checked report")
        _, archive = self.inventory_archive()
        plan_artifact_restore(archive, roots=self.target_roots).apply()
        target = self.target_roots["work"] / key
        extras = {"job.log": b"retained private log", "result.json.pre": b"partial write",
                  "tmp.d/private.sql": b"scratch must never be exported", "input.d/original.zip": b"private input"}
        for name, data in extras.items():
            path = target / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(data)
        replay = plan_artifact_restore(archive, roots=self.target_roots)
        replay.apply()
        replay.rollback()
        for name, data in extras.items():
            self.assertEqual((target / name).read_bytes(), data)
        self.assertEqual((target / "output.d" / "report.txt").read_bytes(), b"checked report")

    def test_retained_scratch_symlink_remains_a_blocker(self):
        identifier = str(uuid4())
        self.payload["records"]["jobs"] = [{"job_uuid": identifier}]
        key = "job_" + identifier.replace("-", "")
        source = self.source_roots["work"] / key
        source.mkdir()
        (source / "result.json").write_text('{}')
        _, archive = self.inventory_archive()
        plan_artifact_restore(archive, roots=self.target_roots).apply()
        target = self.target_roots["work"] / key / "tmp.d"
        target.mkdir()
        (target / "outside").symlink_to(self.root)
        with self.assertRaisesMessage(TransferArchiveError, "filesystem link"):
            plan_artifact_restore(archive, roots=self.target_roots)

    def test_retained_job_byte_collision_has_a_skip_only_conflict(self):
        identifier = str(uuid4())
        self.payload["records"]["jobs"] = [{"job_uuid": identifier}]
        key = "job_" + identifier.replace("-", "")
        source = self.source_roots["work"] / key
        source.mkdir()
        (source / "result.json").write_text('{"source":true}')
        _, archive = self.inventory_archive()
        target = self.target_roots["work"] / key
        target.mkdir(parents=True)
        (target / "result.json").write_text('{"local":true}')
        conflicts = inspect_retained_artifact_conflicts(archive, roots=self.target_roots)
        self.assertEqual(conflicts[0]["key"], "jobs:" + identifier)
        self.assertEqual(conflicts[0]["choices"], ["skip"])
        self.assertEqual((target / "result.json").read_text(), '{"local":true}')

    def test_additive_archive_retains_original_specs_without_adopting_active_configuration(self):
        self.add_delivery()
        specification = json.dumps({"description": "Immutable original", "steps": [{
            "check_ident": "qc_tool.vector.naming", "required": True,
            "parameters": {"reference_year": "2026", "aoi_codes": ["CZ"]},
        }]}, indent=4).encode() + b"\n\n"
        digest = hashlib.sha256(specification).hexdigest()
        self.payload["records"]["definitions"] = [{"id": 7, "digest": digest, "product_ident": "example",
            "document": json.loads(specification), "source_path": "example.json"}]
        configured = self.root / "configured-source"
        configured.mkdir()
        (configured / "example.json").write_bytes(specification)
        self.source_roots["product-0"] = configured
        for kind in ("raster", "vector"):
            directory = self.source_roots["boundaries"] / kind
            directory.mkdir()
            (directory / "source.bin").write_bytes(b"source boundary")
        _, archive = self.inventory_archive()
        selected = additive_archive(archive, {"definitions": {"7"}, "deliveries": {"2"}})
        self.assertEqual(selected.storage, {"boundaries": {}})
        self.assertFalse(any(entry["root"].startswith("product-") or entry["root"] == "boundaries" for entry in selected.entries))
        immutable_key = "product_definitions/.versions/example/" + digest + ".json"
        original_entry = next(entry for entry in selected.entries if entry["key"] == immutable_key)
        self.assertEqual(original_entry["path"], "artifacts/product-0/example.json")
        active = self.target_roots["work"] / "product_definitions" / "example.json"
        active.parent.mkdir(parents=True)
        active.write_bytes(b"retained active config")
        state = active.parent / ".state" / "example.json"
        state.parent.mkdir()
        state.write_bytes(b"retained marker")
        existing_boundary = self.target_roots["boundaries"] / "retained.bin"
        existing_boundary.parent.mkdir(parents=True)
        existing_boundary.write_bytes(b"retained boundary")
        plan_artifact_restore(selected, roots=self.target_roots).apply()
        self.assertEqual((self.target_roots["work"] / immutable_key).read_bytes(), specification)
        self.assertEqual(active.read_bytes(), b"retained active config")
        self.assertEqual(state.read_bytes(), b"retained marker")
        self.assertEqual(existing_boundary.read_bytes(), b"retained boundary")

    def test_additive_archive_drops_skipped_delivery_and_job_branches(self):
        self.add_delivery()
        identifier = str(uuid4())
        self.payload["records"]["jobs"] = [{"job_uuid": identifier}]
        directory = self.source_roots["work"] / ("job_" + identifier.replace("-", ""))
        directory.mkdir()
        (directory / "result.json").write_text('{}')
        _, archive = self.inventory_archive()
        selected = additive_archive(archive, {})
        self.assertEqual(selected.records["records"]["deliveries"], [])
        self.assertEqual(selected.records["records"]["jobs"], [])
        self.assertEqual(selected.entries, ())
        self.assertEqual(selected.directories, ())

    def test_additive_selection_cannot_hide_invalid_full_package(self):
        self.add_delivery()
        _, archive = self.inventory_archive()
        broken = replace(archive, entries=())
        with self.assertRaisesMessage(TransferArchiveError, "missing its verified ZIP"):
            additive_archive(broken, {})

    def test_crash_journal_preserves_ownership_for_later_rollback(self):
        self.add_delivery()
        _, archive = self.inventory_archive()
        plan = plan_artifact_restore(archive, roots=self.target_roots, journal_path=self.journal)
        plan.apply()
        recovered = plan_artifact_restore(archive, roots=self.target_roots, journal_path=self.journal)
        recovered.apply()
        recovered.rollback()
        self.assertFalse((self.target_roots["incoming"] / "alice" / "input.zip").exists())
        self.assertEqual(self.journal_state()["files"], [])

    def test_wal_intent_is_durable_before_final_file_link(self):
        self.add_delivery()
        _, archive = self.inventory_archive()
        plan = plan_artifact_restore(archive, roots=self.target_roots, journal_path=self.journal)
        original_link = os.link
        inspected = []

        def link(source, target, **kwargs):
            if str(target).endswith("input.zip"):
                document = self.journal_state()
                metadata = Path(source).stat()
                inspected.append(document["files"][0]["inode"] == metadata.st_ino)
            return original_link(source, target, **kwargs)

        with patch("qc_tool.database.transfers.artifacts.os.link", side_effect=link):
            plan.apply()
        self.assertEqual(inspected, [True])

    def test_journal_cannot_be_reused_for_another_package_or_roots(self):
        self.add_delivery()
        _, archive = self.inventory_archive()
        plan = plan_artifact_restore(archive, roots=self.target_roots, journal_path=self.journal)
        plan.apply()
        with self.assertRaises(TransferArchiveError):
            plan_artifact_restore(replace(archive, package_sha256="0" * 64), roots=self.target_roots, journal_path=self.journal)

    def test_torn_last_journal_append_is_discarded_before_recovery(self):
        self.add_delivery()
        _, archive = self.inventory_archive()
        plan = plan_artifact_restore(archive, roots=self.target_roots, journal_path=self.journal)
        plan.apply()
        intact = self.journal.read_bytes()
        with self.journal.open("ab") as stream:
            stream.write(b'{"event":"add","files":[')
        recovered = plan_artifact_restore(archive, roots=self.target_roots, journal_path=self.journal)
        self.assertEqual(self.journal.read_bytes(), intact)
        recovered.rollback()
        self.assertFalse((self.target_roots["incoming"] / "alice" / "input.zip").exists())

    def test_wal_size_grows_linearly_with_file_count(self):
        uuid = str(uuid4())
        self.payload["records"]["jobs"] = [{"job_uuid": uuid}]
        root = self.source_roots["work"] / ("job_" + uuid.replace("-", "")) / "output.d"
        root.mkdir(parents=True)
        for index in range(100):
            (root / ("file-" + str(index))).write_bytes(b"x")
        _, archive = self.inventory_archive()
        plan = plan_artifact_restore(archive, roots=self.target_roots, journal_path=self.journal)
        plan.apply()
        self.assertLess(self.journal.stat().st_size, 40_000)
        self.assertEqual(len(self.journal_state()["files"]), 100)

    def test_mutating_namespace_and_account_artifact_injection_are_rejected(self):
        source = self.root / "secret"
        source.write_bytes(b"x")
        write_archive(self.package, {}, self.payload, [ArtifactSource("work", "worker.token", source)], storage={"boundaries": {}})
        with self.assertRaises(TransferArchiveError):
            plan_artifact_restore(inspect_archive(self.package), roots=self.target_roots)
        self.package.unlink()
        write_archive(self.package, {}, {"profile": "accounts"}, [ArtifactSource("incoming", "a.zip", source)])
        with self.assertRaises(TransferArchiveError):
            plan_artifact_restore(inspect_archive(self.package), roots=self.target_roots)

    def test_missing_active_upload_or_original_specification_fails_export(self):
        source, row = self.add_delivery()
        source.unlink()
        with self.assertRaises(TransferArchiveError):
            collect_artifacts(self.payload, roots=self.source_roots)
        row["is_deleted"] = True
        self.payload["records"]["definitions"] = [{"digest": "a" * 64}]
        with self.assertRaises(TransferArchiveError):
            collect_artifacts(self.payload, roots=self.source_roots)

    def test_missing_historical_job_artifacts_are_explicit_and_runtime_secrets_excluded(self):
        uuid = str(uuid4())
        self.payload["records"]["jobs"] = [{"job_uuid": uuid}]
        (self.source_roots["work"] / "worker.token").write_bytes(b"secret")
        (self.source_roots["work"] / "frontend.log").write_bytes(b"private")
        inventory = collect_artifacts(self.payload, roots=self.source_roots)
        self.assertFalse(inventory.sources)
        self.assertTrue(any(uuid in message for message in inventory.warnings))

    def test_managed_boundaries_are_regular_package_files_with_validated_generated_links(self):
        generation = "gen-" + "a" * 32
        root = self.source_roots["boundaries"]
        for name in ("raster", "vector"):
            directory = root / ".boundary-generations" / generation / name
            directory.mkdir(parents=True)
            (directory / "test.dat").write_bytes(name.encode())
        (root / ".boundary-current").symlink_to(".boundary-generations/" + generation)
        for name in ("raster", "vector"):
            (root / name).symlink_to(".boundary-current/" + name)
        _, archive = self.inventory_archive()
        self.assertEqual(archive.storage, {"boundaries": {"mode": "managed", "generation": generation}})
        plan = plan_artifact_restore(archive, roots=self.target_roots, journal_path=self.journal)
        plan.apply()
        self.assertEqual((self.target_roots["boundaries"] / "raster" / "test.dat").read_bytes(), b"raster")
        directory = self.target_roots["boundaries"] / ".boundary-generations" / generation
        self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o550)
        recovered = plan_artifact_restore(archive, roots=self.target_roots, journal_path=self.journal)
        recovered.rollback()
        self.assertFalse(os.path.lexists(self.target_roots["boundaries"] / ".boundary-current"))

    def test_original_source_file_changes_are_detected_again_during_copy(self):
        self.add_delivery()
        _, archive = self.inventory_archive()
        plan = plan_artifact_restore(archive, roots=self.target_roots)
        entry = archive.entries[0]
        with zipfile.ZipFile(self.package) as package:
            files = {item.filename: package.read(item.filename) for item in package.infolist()}
        files[entry["path"]] = b"tampered"
        with zipfile.ZipFile(self.package, "w") as package:
            for name, payload in files.items():
                package.writestr(name, payload)
        with self.assertRaises(TransferArchiveError):
            plan.apply()
        self.assertFalse((self.target_roots["incoming"] / "alice" / "input.zip").exists())

    def test_uploaded_specifications_preserve_original_bytes_and_activation(self):
        document = {"description": "Original specification", "steps": [{
            "check_ident": "qc_tool.vector.naming", "required": True,
            "parameters": {"reference_year": "2026", "aoi_codes": ["CZ"]},
        }]}
        original = json.dumps(document, indent=4).encode() + b"\n\n"
        digest = hashlib.sha256(original).hexdigest()
        versions = self.source_roots["work"] / "product_definitions" / ".versions" / "example"
        versions.mkdir(parents=True)
        (versions / (digest + ".json")).write_bytes(original)
        states = self.source_roots["work"] / "product_definitions" / ".state"
        states.mkdir()
        (states / "example.json").write_text(json.dumps({"active": True, "digest": digest}))
        self.payload["records"]["definitions"] = [{"digest": digest, "product_ident": "example", "document": document, "source_path": "upload:example.json"}]
        _, archive = self.inventory_archive()
        plan = plan_artifact_restore(archive, roots=self.target_roots)
        plan.apply()
        restored = self.target_roots["work"] / "product_definitions" / ".versions" / "example" / (digest + ".json")
        self.assertEqual(restored.read_bytes(), original)
        self.assertEqual((versions / (digest + ".json")).read_bytes(), original)
        self.assertEqual(json.loads((self.target_roots["work"] / "product_definitions" / ".state" / "example.json").read_bytes())["digest"], digest)

    def test_published_receipt_restores_complete_immutable_inventory(self):
        source, _ = self.add_delivery()
        submission_uuid, job_uuid = str(uuid4()), str(uuid4())
        self.payload["records"]["jobs"] = [{"job_uuid": job_uuid}]
        key = "release-3-example/product-unit-4-cz/submission-" + submission_uuid + ".d"
        directory = self.source_roots["submissions"] / key
        (directory / "input.d").mkdir(parents=True)
        (directory / "output.d").mkdir()
        (directory / "input.d" / "input.zip").write_bytes(source.read_bytes())
        (directory / "SUBMITTED").write_bytes(b"")
        (directory / "job.log").write_bytes(b"retained publication log\n")
        inventory = []
        for name in ("input.d/input.zip", "SUBMITTED", "job.log"):
            data = (directory / name).read_bytes()
            inventory.append({"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        manifest = {"schema_version": 2, "submission_id": submission_uuid, "delivery_id": 2,
                    "job_id": job_uuid, "product_release_id": 3, "product_unit_id": 4,
                    "product_unit_code": "CZ", "submitted_product_unit_code": "CZ",
                    "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "storage": "local",
                    "requested_at": "2026-01-01T00:00:00+00:00", "files": inventory}
        digest = hashlib.sha256(canonical_json(manifest)).hexdigest()
        original_manifest = canonical_json({**manifest, "artifact_sha256": digest})
        (directory / "submission-manifest.json").write_bytes(original_manifest)
        self.payload["records"]["submissions"] = [{
            "submission_uuid": submission_uuid, "delivery_id": 2, "job_id": job_uuid,
            "product_release_id": 3, "product_unit_id": 4, "product_unit_code": "CZ",
            "verified_product_unit_code": "CZ", "input_digest": manifest["input_sha256"],
            "artifact_digest": digest, "artifact_key": key, "publication_state": "published",
            "requested_at": "2026-01-01T00:00:00Z",
        }]
        _, archive = self.inventory_archive()
        plan = plan_artifact_restore(archive, roots=self.target_roots)
        plan.apply()
        target = self.target_roots["submissions"] / key
        self.assertEqual((target / "submission-manifest.json").read_bytes(), original_manifest)
        self.assertEqual((target / "job.log").read_bytes(), b"retained publication log\n")
        self.assertTrue((target / "output.d").is_dir())
        broken = replace(archive, entries=tuple(item for item in archive.entries if item["key"] != key + "/job.log"))
        with self.assertRaises(TransferArchiveError):
            plan_artifact_restore(broken, roots=self.target_roots)
        (target / "unexpected.txt").write_bytes(b"keep existing foreign file")
        with self.assertRaisesMessage(TransferArchiveError, "outside the package inventory"):
            plan_artifact_restore(archive, roots=self.target_roots)
        self.assertEqual((target / "unexpected.txt").read_bytes(), b"keep existing foreign file")

    def test_failure_after_committed_database_can_retain_owned_files(self):
        self.add_delivery()
        _, archive = self.inventory_archive()
        plan = plan_artifact_restore(archive, roots=self.target_roots, journal_path=self.journal)
        plan.apply()
        with patch.object(plan, "_activate_boundaries", side_effect=TransferArchiveError("recovery unavailable")):
            with self.assertRaises(TransferArchiveError):
                plan.apply(rollback_on_error=False)
        self.assertTrue((self.target_roots["incoming"] / "alice" / "input.zip").is_file())
