#!/usr/bin/env python3
"""Audit a legacy snapshot, or import it into a new offline SQLite rehearsal.

This script never connects to production. Run it in the frontend Python
environment. The source must be a complete UTF-8 plain PostgreSQL pg_dump or a
reviewed mixed-history interchange from scripts.migration.legacy.prepare_sources. The
existing importer parses COPY data and never executes the source SQL.
"""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat
import subprocess
import sys
import tempfile


REPOSITORY = Path(__file__).resolve().parents[3]
MANAGE = [sys.executable, "-m", "qc_tool.frontend.manage"]
COUNT_TABLES = {
    "users": "auth_user",
    "deliveries": "execution_delivery",
    "jobs": "execution_job",
    "storage_sources": "storage_delivery_source",
    "admin_log_entries": "django_admin_log",
    "product_grants": "account_product_grant",
}
# Carry interpreter/runtime locations, but no inherited application settings,
# PostgreSQL connection details, browser credentials, or arbitrary secrets.
RUNTIME_ENVIRONMENT = (
    "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR", "TEMP",
    "TMP", "PYTHONHOME", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "GDAL_DATA",
    "PROJ_LIB", "PROJ_DATA", "SYSTEMROOT", "WINDIR",
)


class RehearsalError(Exception):
    """An operator-safe error without source row contents or secrets."""


def fingerprint(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise RehearsalError("The source must be a regular file.")
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return {"sha256": digest.hexdigest(), "size_bytes": size}


def copy_private(source_path, destination):
    """Preserve original bytes and refuse any occupied destination."""
    before = fingerprint(source_path)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as target, source_path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            target.write(block)
        target.flush()
        os.fsync(target.fileno())
    if fingerprint(destination) != before or fingerprint(source_path) != before:
        raise RehearsalError("The source changed while copying. Use a completed immutable snapshot and a new run directory.")
    return before


def write_json(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as target:
        json.dump(value, target, indent=2, sort_keys=True)
        target.write("\n")


def isolated_environment(run_dir):
    environment = {key: os.environ[key] for key in RUNTIME_ENVIRONMENT if key in os.environ}
    environment.update({
        "PYTHONPATH": str(REPOSITORY / "src"),
        "DJANGO_SETTINGS_MODULE": "qc_tool.frontend.settings",
        "DJANGO_SECRET_KEY": secrets.token_urlsafe(32),
        "DJANGO_ALLOWED_HOSTS": "localhost,127.0.0.1,testserver",
        "DJANGO_DEBUG": "no",
        "QC_TOOL_ENVIRONMENT": "test",
        "DB_ENGINE": "sqlite",
        "FRONTEND_DB_PATH": str(run_dir / "target.sqlite3"),
        "WORK_DIR": str(run_dir / "work"),
        "INCOMING_DIR": str(run_dir / "incoming"),
        "BOUNDARY_DIR": str(run_dir / "boundaries"),
        "PRODUCT_DIRS": str(run_dir / "products"),
        "SUBMISSION_DIR": str(run_dir / "submissions"),
        "UPDATE_JOB_STATUSES": "no",
        "MAINTENANCE_MODE": "yes",
        "PYTHONUNBUFFERED": "1",
    })
    return environment


def run_stage(name, arguments, environment, stages):
    print(f"{name}...", flush=True)
    result = subprocess.run(
        MANAGE + list(arguments), cwd=REPOSITORY, env=environment,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    stages.append({"stage": name, "exit_code": result.returncode})
    # Do not print/store child output: unexpected tracebacks can contain data.
    if result.returncode:
        raise RehearsalError(
            f"{name} failed (exit {result.returncode}). The run is incomplete; "
            "use the frontend Python environment and check source compatibility. "
            "Child output is suppressed to protect source data."
        )


def reconcile(database_path, dry_run, applied, *, mixed_history=False):
    """Independent, read-only aggregate checks of the imported SQLite database."""
    if applied.get("source_sha256") != dry_run.get("source_sha256"):
        raise RehearsalError("Dry-run and applied source checksums differ.")
    if applied.get("planned") != dry_run.get("planned"):
        raise RehearsalError("Dry-run and applied import plans differ.")
    checks = {}
    counts = {}
    uri = database_path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        def scalar(sql, parameters=()):
            return connection.execute(sql, parameters).fetchone()[0]

        checks["sqlite_integrity"] = scalar("PRAGMA integrity_check") == "ok"
        checks["foreign_keys"] = not connection.execute("PRAGMA foreign_key_check").fetchone()
        for key, table in COUNT_TABLES.items():
            counts[key] = scalar(f'SELECT COUNT(*) FROM "{table}"')
            checks[key] = counts[key] == dry_run["planned"][key] == applied["imported"][key]
        history = dry_run["historical_records"]
        counts["historical_submission_dates"] = scalar(
            "SELECT COUNT(*) FROM execution_delivery WHERE date_submitted IS NOT NULL"
        )
        counts["deleted_deliveries"] = scalar(
            "SELECT COUNT(*) FROM execution_delivery WHERE is_deleted = 1"
        )
        checks["historical_submission_dates"] = counts["historical_submission_dates"] == history.get("submitted_deliveries", 0)
        checks["deleted_deliveries"] = counts["deleted_deliveries"] == history.get("deleted_deliveries", 0)
        counts["runnable_jobs"] = scalar(
            "SELECT COUNT(*) FROM execution_job WHERE job_status IN (?, ?)",
            ("waiting", "running"),
        )
        checks["no_runnable_legacy_jobs"] = counts["runnable_jobs"] == 0
        source_states = dry_run["source_job_states"]
        expected_states = dict(source_states)
        unfinished = expected_states.pop("waiting", 0) + expected_states.pop("running", 0)
        if unfinished:
            expected_states["worker lost"] = expected_states.get("worker lost", 0) + unfinished
        actual_states = dict(connection.execute(
            "SELECT job_status, COUNT(*) FROM execution_job GROUP BY job_status"
        ))
        checks["job_states"] = actual_states == expected_states
        counts["job_states"] = actual_states
        checks["no_invented_delivery_evidence"] = scalar(
            "SELECT COUNT(*) FROM execution_delivery "
            "WHERE verified_product_unit_code IS NOT NULL OR content_sha256 IS NOT NULL"
        ) == 0
        checks["no_invented_job_evidence"] = scalar(
            "SELECT COUNT(*) FROM execution_job "
            "WHERE verified_product_unit_code IS NOT NULL OR input_sha256 != '' "
            "OR request_source IS NOT NULL OR product_release_id IS NOT NULL OR qc_definition_id IS NOT NULL"
        ) == 0
        checks["no_copied_s3_credentials"] = scalar(
            "SELECT COUNT(*) FROM storage_delivery_source WHERE credential_ref != ''"
        ) == 0
        if mixed_history:
            counts["users_requiring_password_provisioning"] = scalar(
                "SELECT COUNT(*) FROM auth_user WHERE password LIKE '!%'"
            )
            checks["no_restored_stale_passwords"] = counts["users_requiring_password_provisioning"] == counts["users"]
        for table in (
            "catalog_product", "publication_submission", "publication_conflict",
            "publication_conflict_event", "publication_review_event", "account_api_token",
            "django_session",
        ):
            counts[table] = scalar(f'SELECT COUNT(*) FROM "{table}"')
            checks[f"empty_{table}"] = counts[table] == 0
    return {"passed": all(checks.values()), "checks": checks, "target_counts": counts}


def create_run_directory(requested):
    if requested is None:
        return Path(tempfile.mkdtemp(prefix="qc-legacy-rehearsal-")).resolve()
    path = requested.expanduser().absolute()
    # mkdir rejects existing directories/files and symlinks; no parent creation.
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        raise RehearsalError("The run directory already exists. Choose a new directory; existing data is never reset.") from None
    return path.resolve()


def ensure_private_directory(path):
    # The dry-run child imports common.setup_config(), which may already have
    # created WORK_DIR. These are owned paths inside this new private run, not
    # existing application storage to reset or reuse.
    if path.is_symlink():
        raise RehearsalError("A local run subdirectory is a symlink; keep this run offline and use a new directory.")
    path.mkdir(mode=0o700, exist_ok=True)
    if not path.is_dir():
        raise RehearsalError("A local run storage path is not a directory.")
    path.chmod(0o700)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path, help="Complete UTF-8 plain pg_dump or prepared mixed-history interchange; raw directory/table exports are unsupported.")
    parser.add_argument("--apply", action="store_true", help="Import into a new offline SQLite rehearsal; otherwise audit only.")
    parser.add_argument("--output-dir", type=Path, help="New private run directory (default: a new temporary directory). Must not exist.")
    parser.add_argument("--access-map", type=Path, help="Reviewed user role/product grant JSON. Original bytes are copied privately.")
    arguments = parser.parse_args(argv)
    source = arguments.dump.expanduser().resolve()
    run_dir = None
    manifest = {"started_at_utc": datetime.now(timezone.utc).isoformat(),
                "mode": "local_rehearsal" if arguments.apply else "dry_run",
                "status": "incomplete", "stages": []}
    return_code = 1
    old_umask = os.umask(0o077)
    try:
        if not source.is_file():
            raise RehearsalError("Supply a complete plain pg_dump file, not a directory or table export.")
        run_dir = create_run_directory(arguments.output_dir)
        print(f"Private run directory: {run_dir}", flush=True)
        snapshot = run_dir / "snapshot.sql"
        manifest["source"] = copy_private(source, snapshot)
        with snapshot.open("rb") as stream:
            mixed_history = b"MIXED AVAILABLE HISTORY" in stream.readline(512)
        manifest["source_kind"] = "mixed_available_history_import_interchange" if mixed_history else "plain_legacy_dump"
        if mixed_history:
            manifest["password_policy"] = "All current users require explicit target password provisioning; no older hashes are restored."
            provenance = source.with_name("source-preparation-manifest.json")
            if provenance.is_file():
                manifest["source_provenance_file"] = copy_private(provenance, run_dir / "source-preparation-manifest.json")
                prepared_provenance = json.loads((run_dir / "source-preparation-manifest.json").read_text(encoding="utf-8"))
                if prepared_provenance.get("kind") != manifest["source_kind"] or prepared_provenance.get("prepared") != manifest["source"]:
                    raise RehearsalError("The source preparation manifest does not match this mixed-history interchange.")
                manifest["mixed_source_limitations"] = prepared_provenance.get("limitations", [])
        environment = isolated_environment(run_dir)
        access_options = []
        access_source = None
        if arguments.access_map:
            access_source = arguments.access_map.expanduser().resolve()
            access_snapshot = run_dir / "access-map.json"
            manifest["access_map"] = copy_private(access_source, access_snapshot)
            access_options = ["--access-map", str(access_snapshot)]
        dry_path = run_dir / "dry-run-report.json"
        run_stage("Validate snapshot (dry run)", [
            "import_legacy_dump", str(snapshot), "--dry-run", "--report", str(dry_path),
            *access_options,
        ], environment, manifest["stages"])
        dry_run = json.loads(dry_path.read_text(encoding="utf-8"))
        if dry_run.get("source_sha256") != manifest["source"]["sha256"]:
            raise RehearsalError("The importer source checksum does not match the copied snapshot.")
        manifest["planned"] = dry_run["planned"]
        manifest["warnings"] = dry_run["warnings"]
        if arguments.apply:
            target = run_dir / "target.sqlite3"
            if target.exists() or target.is_symlink():
                raise RehearsalError("The local target already exists; nothing is reset or merged.")
            for directory in ("work", "incoming", "boundaries", "products", "submissions"):
                ensure_private_directory(run_dir / directory)
            for action in ("plan", "apply", "check"):
                run_stage(f"Database {action}", ["database", action], environment, manifest["stages"])
            applied_path = run_dir / "applied-report.json"
            run_stage("Import into new local database", [
                "import_legacy_dump", str(snapshot), "--apply", "--target-database", str(target),
                "--report", str(applied_path), *access_options,
            ], environment, manifest["stages"])
            run_stage("Database check after import", ["database", "check"], environment, manifest["stages"])
            applied = json.loads(applied_path.read_text(encoding="utf-8"))
            reconciliation = reconcile(target, dry_run, applied, mixed_history=mixed_history)
            write_json(run_dir / "reconciliation-report.json", reconciliation)
            if not reconciliation["passed"]:
                raise RehearsalError("Aggregate reconciliation failed. Keep this target offline and inspect reconciliation-report.json.")
            manifest["reconciliation_passed"] = True
        if fingerprint(source) != manifest["source"] or fingerprint(snapshot) != manifest["source"]:
            raise RehearsalError("The source or local snapshot changed during the run.")
        if access_source and (
            fingerprint(access_source) != manifest["access_map"]
            or fingerprint(run_dir / "access-map.json") != manifest["access_map"]
        ):
            raise RehearsalError("The access map changed during the run.")
        manifest["source_unchanged"] = True
        manifest["status"] = "passed"
        print("Local import and aggregate reconciliation passed." if arguments.apply else "Dry run passed; no database was created.", flush=True)
        print(f"Source SHA-256: {manifest['source']['sha256']}", flush=True)
        print("Counts: " + json.dumps(manifest["planned"], sort_keys=True), flush=True)
        return_code = 0
    except (RehearsalError, OSError, ValueError, KeyError, sqlite3.Error):
        # OS/SQL/JSON exceptions can carry source text or connection details.
        # Only our explicitly safe error class is exposed to ordinary output.
        error = sys.exc_info()[1]
        message = str(error) if isinstance(error, RehearsalError) else "The local rehearsal failed. Check file permissions, source compatibility and the frontend Python environment."
        manifest["error"] = message
        print(message, file=sys.stderr, flush=True)
        return_code = 1
    finally:
        manifest["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        if run_dir is not None:
            try:
                write_json(run_dir / "rehearsal-manifest.json", manifest)
            except OSError:
                print("The manifest could not be written; keep the run directory for inspection.", file=sys.stderr)
                return_code = 1
        os.umask(old_umask)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
