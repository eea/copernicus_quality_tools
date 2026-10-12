"""Stdlib safety checks; no application database or source data is consulted."""

import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest
from unittest.mock import patch


from scripts.migration.legacy import rehearse as rehearsal


class LocalRehearsalSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def test_existing_directory_and_symlink_are_never_reused(self):
        occupied = self.directory / "occupied"
        occupied.mkdir()
        existing_database = occupied / "target.sqlite3"
        existing_database.write_bytes(b"existing valuable local data")
        alias = self.directory / "alias"
        alias.symlink_to(occupied, target_is_directory=True)
        for requested in (occupied, alias):
            with self.assertRaises(rehearsal.RehearsalError):
                rehearsal.create_run_directory(requested)
        self.assertEqual(existing_database.read_bytes(), b"existing valuable local data")

    def test_snapshot_keeps_original_bytes_and_refuses_overwrite(self):
        source = self.directory / "production.sql"
        original = b"private snapshot\r\nwith tab\tand COPY escapes\\N\n"
        source.write_bytes(original)
        snapshot = self.directory / "snapshot.sql"
        digest = rehearsal.copy_private(source, snapshot)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(snapshot.read_bytes(), original)
        self.assertEqual(digest, rehearsal.fingerprint(source))
        self.assertEqual(stat.S_IMODE(snapshot.stat().st_mode), 0o600)
        with self.assertRaises(FileExistsError):
            rehearsal.copy_private(source, snapshot)
        self.assertEqual(snapshot.read_bytes(), original)

    def test_source_change_during_copy_fails(self):
        source = self.directory / "production.sql"
        source.write_bytes(b"before")
        before = rehearsal.fingerprint(source)
        after = {"sha256": "changed", "size_bytes": 6}
        with patch.object(rehearsal, "fingerprint", side_effect=[before, before, after]):
            with self.assertRaisesRegex(rehearsal.RehearsalError, "changed while copying"):
                rehearsal.copy_private(source, self.directory / "snapshot.sql")

    def test_child_environment_cannot_inherit_production_database_or_secrets(self):
        inherited = {
            "PATH": "/test/runtime/bin", "POSTGRES_HOST": "production.example",
            "POSTGRES_PASSWORD": "synthetic-private", "DB_ENGINE": "postgres",
            "FRONTEND_DB_PATH": "/existing/production.sqlite3",
            "DJANGO_SETTINGS_MODULE": "unsafe.settings", "PRIVATE_API_TOKEN": "synthetic-private",
            "PRODUCT_DIRS": "/production/specifications", "WORK_DIR": "/production/storage",
        }
        with patch.dict(os.environ, inherited, clear=True):
            environment = rehearsal.isolated_environment(self.directory)
        self.assertEqual(environment["PATH"], inherited["PATH"])
        self.assertEqual(environment["DB_ENGINE"], "sqlite")
        self.assertEqual(environment["FRONTEND_DB_PATH"], str(self.directory / "target.sqlite3"))
        self.assertEqual(environment["DJANGO_SETTINGS_MODULE"], "qc_tool.frontend.settings")
        self.assertEqual(environment["PRODUCT_DIRS"], str(self.directory / "products"))
        self.assertFalse(any(key.startswith("POSTGRES") for key in environment))
        self.assertNotIn("PRIVATE_API_TOKEN", environment)
        self.assertNotIn("synthetic-private", environment.values())

    def test_failed_child_output_is_not_exposed(self):
        child = rehearsal.subprocess.CompletedProcess([], 1, "synthetic secret row", "synthetic password hash")
        with patch.object(rehearsal.subprocess, "run", return_value=child), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(rehearsal.RehearsalError) as failure:
                rehearsal.run_stage("Import", ["import_legacy_dump"], {}, [])
        self.assertNotIn("secret row", str(failure.exception))
        self.assertNotIn("password hash", str(failure.exception))

    def test_default_audit_creates_no_database_and_records_checksum(self):
        source = self.directory / "production.sql"
        source.write_bytes(b"synthetic snapshot")
        run_dir = self.directory / "audit"
        planned = {key: 0 for key in rehearsal.COUNT_TABLES}

        def synthetic_dry_run(name, arguments, environment, stages):
            self.assertIn("--dry-run", arguments)
            self.assertNotIn("--apply", arguments)
            report = Path(arguments[arguments.index("--report") + 1])
            rehearsal.write_json(report, {
                "source_sha256": rehearsal.fingerprint(source)["sha256"],
                "planned": planned, "warnings": [],
            })
            stages.append({"stage": name, "exit_code": 0})

        with patch.object(rehearsal, "run_stage", side_effect=synthetic_dry_run), contextlib.redirect_stdout(io.StringIO()):
            result = rehearsal.main([str(source), "--output-dir", str(run_dir)])
        self.assertEqual(result, 0)
        self.assertFalse((run_dir / "target.sqlite3").exists())
        manifest = json.loads((run_dir / "rehearsal-manifest.json").read_text())
        self.assertEqual(manifest["status"], "passed")
        self.assertTrue(manifest["source_unchanged"])
        self.assertEqual(stat.S_IMODE(run_dir.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((run_dir / "rehearsal-manifest.json").stat().st_mode), 0o600)

    def make_database(self, database=None):
        database = database or self.directory / "target.sqlite3"
        with contextlib.closing(sqlite3.connect(database)) as connection:
            connection.executescript("""
                CREATE TABLE auth_user (id INTEGER PRIMARY KEY);
                CREATE TABLE execution_delivery (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES auth_user(id),
                    date_submitted TEXT, is_deleted INTEGER, verified_product_unit_code TEXT, content_sha256 TEXT);
                CREATE TABLE execution_job (id INTEGER PRIMARY KEY, job_status TEXT, verified_product_unit_code TEXT,
                    input_sha256 TEXT DEFAULT '', request_source TEXT, product_release_id INTEGER, qc_definition_id INTEGER);
                CREATE TABLE storage_delivery_source (id INTEGER PRIMARY KEY, credential_ref TEXT DEFAULT '');
                CREATE TABLE django_admin_log (id INTEGER PRIMARY KEY);
                CREATE TABLE account_product_grant (id INTEGER PRIMARY KEY);
                CREATE TABLE catalog_product (id INTEGER PRIMARY KEY);
                CREATE TABLE publication_submission (id INTEGER PRIMARY KEY);
                CREATE TABLE publication_conflict (id INTEGER PRIMARY KEY);
                CREATE TABLE publication_conflict_event (id INTEGER PRIMARY KEY);
                CREATE TABLE publication_review_event (id INTEGER PRIMARY KEY);
                CREATE TABLE account_api_token (id INTEGER PRIMARY KEY);
                CREATE TABLE django_session (id INTEGER PRIMARY KEY);
                INSERT INTO auth_user VALUES (1);
                INSERT INTO execution_delivery VALUES (1, 1, '2020-01-01', 0, NULL, NULL);
                INSERT INTO execution_job (id, job_status) VALUES (1, 'worker lost');
            """)
        planned = {key: 0 for key in rehearsal.COUNT_TABLES}
        planned.update(users=1, deliveries=1, jobs=1)
        dry_run = {"source_sha256": "synthetic", "planned": planned,
                   "historical_records": {"submitted_deliveries": 1}, "source_job_states": {"running": 1}}
        applied = {"source_sha256": "synthetic", "planned": planned, "imported": planned}
        return database, dry_run, applied

    def test_apply_accepts_owned_work_directory_created_by_dry_run_child(self):
        source = self.directory / "production.sql"
        source.write_bytes(b"synthetic snapshot")
        run_dir = self.directory / "rehearsal"
        planned = {key: 0 for key in rehearsal.COUNT_TABLES}
        planned.update(users=1, deliveries=1, jobs=1)
        dry_run = {"source_sha256": rehearsal.fingerprint(source)["sha256"], "planned": planned,
                   "warnings": [], "historical_records": {"submitted_deliveries": 1},
                   "source_job_states": {"running": 1}}

        def synthetic_child(name, arguments, environment, stages):
            if "--dry-run" in arguments:
                # Real common.setup_config has this side effect before returning
                # an import audit; the wrapper must tolerate its owned directory.
                Path(environment["WORK_DIR"]).mkdir()
                report = Path(arguments[arguments.index("--report") + 1])
                rehearsal.write_json(report, dry_run)
            elif arguments == ["database", "apply"]:
                self.make_database(run_dir / "target.sqlite3")
            elif "import_legacy_dump" in arguments and "--apply" in arguments:
                report = Path(arguments[arguments.index("--report") + 1])
                rehearsal.write_json(report, {**dry_run, "imported": planned})
            stages.append({"stage": name, "exit_code": 0})

        with patch.object(rehearsal, "run_stage", side_effect=synthetic_child), contextlib.redirect_stdout(io.StringIO()):
            result = rehearsal.main([str(source), "--apply", "--output-dir", str(run_dir)])
        self.assertEqual(result, 0)
        manifest = json.loads((run_dir / "rehearsal-manifest.json").read_text())
        self.assertEqual(manifest["status"], "passed")
        self.assertTrue(manifest["reconciliation_passed"])
        self.assertEqual(stat.S_IMODE((run_dir / "work").stat().st_mode), 0o700)
        self.assertIn("Database plan", {item["stage"] for item in manifest["stages"]})

    def test_owned_run_storage_symlinks_are_refused(self):
        external = self.directory / "external"
        external.mkdir()
        owned_path = self.directory / "work"
        owned_path.symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(rehearsal.RehearsalError, "symlink"):
            rehearsal.ensure_private_directory(owned_path)
        self.assertEqual(list(external.iterdir()), [])

    def test_reconciliation_accepts_history_but_rejects_invented_evidence(self):
        database, dry_run, applied = self.make_database()
        self.assertTrue(rehearsal.reconcile(database, dry_run, applied)["passed"])
        before = rehearsal.fingerprint(database)
        rehearsal.reconcile(database, dry_run, applied)
        self.assertEqual(before, rehearsal.fingerprint(database))
        with contextlib.closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("UPDATE execution_delivery SET content_sha256 = 'invented'")
        report = rehearsal.reconcile(database, dry_run, applied)
        self.assertFalse(report["passed"])
        self.assertFalse(report["checks"]["no_invented_delivery_evidence"])

    def test_reconciliation_detects_foreign_keys_missing_history_and_runnable_jobs(self):
        database, dry_run, applied = self.make_database()
        with contextlib.closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("UPDATE execution_delivery SET user_id = 99, date_submitted = NULL")
            connection.execute("UPDATE execution_job SET job_status = 'running'")
        report = rehearsal.reconcile(database, dry_run, applied)
        self.assertFalse(report["passed"])
        for check in ("foreign_keys", "historical_submission_dates", "no_runnable_legacy_jobs", "job_states"):
            self.assertFalse(report["checks"][check])

    def test_mixed_history_reconciliation_requires_unusable_passwords(self):
        database, dry_run, applied = self.make_database()
        with contextlib.closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("ALTER TABLE auth_user ADD COLUMN password TEXT")
            connection.execute("UPDATE auth_user SET password = 'synthetic-older-hash'")
        report = rehearsal.reconcile(database, dry_run, applied, mixed_history=True)
        self.assertFalse(report["passed"])
        self.assertFalse(report["checks"]["no_restored_stale_passwords"])
        with contextlib.closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("UPDATE auth_user SET password = '!legacy-admin-export'")
        report = rehearsal.reconcile(database, dry_run, applied, mixed_history=True)
        self.assertTrue(report["passed"])
        self.assertEqual(report["target_counts"]["users_requiring_password_provisioning"], 1)


if __name__ == "__main__":
    unittest.main()
