#!/usr/bin/env python3
"""Prepare explicitly mixed available history for the offline legacy importer.

An older complete SQL snapshot supplies storage and audit metadata; newer
delivery/job CSVs supply those complete tables; read-only admin JSON supplies
current user fields. All current passwords become unusable. The result is an
import interchange, NOT a coherent current production database backup.
"""

import argparse
import csv
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from scripts.migration.legacy.rehearse import (
    REPOSITORY, RehearsalError, copy_private, create_run_directory,
    fingerprint, write_json,
)

sys.path.insert(0, str(REPOSITORY / "src"))
from qc_tool.database.legacy.dump import read_legacy_dump  # stdlib-only parser


USER_COLUMNS = (
    "id", "password", "last_login", "is_superuser", "username", "first_name",
    "last_name", "email", "is_staff", "is_active", "date_joined",
)
USER_LIST_METADATA = {"source_groups", "source_user_permissions"}
USER_METADATA = USER_LIST_METADATA | {"source_timezone"}
DELIVERY_COLUMNS = (
    "id", "filename", "product_ident", "date_uploaded", "date_submitted", "user_id",
    "product_description", "size_bytes", "is_deleted", "s3_id", "aoi_code",
)
JOB_COLUMNS = (
    "job_uuid", "date_created", "date_started", "date_finished", "job_status",
    "product_ident", "skip_steps", "worker_url", "delivery_id", "product_description", "aoi_code",
)
NULLABLE_COLUMNS = {
    "dashboard_delivery": {"product_ident", "date_submitted", "user_id", "product_description", "s3_id", "aoi_code"},
    "dashboard_job": {"date_started", "date_finished", "skip_steps", "worker_url", "aoi_code"},
}
CLEAR_LINK_TABLES = ("auth_user_groups", "auth_user_user_permissions", "auth_group_permissions")


def read_table_csv(path, table, columns):
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(columns):
            raise RehearsalError(f"{table}: unsupported CSV columns or order.")
        rows = []
        for row_number, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise RehearsalError(f"{table}: CSV column count mismatch at row {row_number}.")
            rows.append({
                key: None if value == "" and key in NULLABLE_COLUMNS[table] else value
                for key, value in row.items()
            })
    return rows


def read_current_users(path):
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("users"), list):
        raise RehearsalError("Current admin JSON must contain a users list.")
    users = []
    timestamps_localized = 0
    source_timezones = set()
    for row_number, row in enumerate(document["users"], start=1):
        if not isinstance(row, dict) or set(row) - set(USER_COLUMNS) - USER_METADATA:
            raise RehearsalError(f"Current admin user row {row_number}: unsupported fields.")
        if set(USER_COLUMNS) - {"password"} - set(row):
            raise RehearsalError(f"Current admin user row {row_number}: missing canonical fields.")
        if any(not isinstance(row.get(name, []), list) for name in USER_LIST_METADATA):
            raise RehearsalError(f"Current admin user row {row_number}: source access metadata must be lists.")
        source_timezone = None
        if "source_timezone" in row:
            if not isinstance(row["source_timezone"], str) or not row["source_timezone"]:
                raise RehearsalError(f"Current admin user row {row_number}: source_timezone must name a timezone.")
            try:
                source_timezone = ZoneInfo(row["source_timezone"])
            except (ZoneInfoNotFoundError, ValueError):
                raise RehearsalError(f"Current admin user row {row_number}: unsupported source timezone.") from None
            source_timezones.add(row["source_timezone"])
        converted = {}
        for column in USER_COLUMNS:
            # A current web view cannot prove the current stored password hash.
            # Never restore the older snapshot's credentials into current users.
            value = "!legacy-admin-export" if column == "password" else row[column]
            if column == "id" and isinstance(value, int) and not isinstance(value, bool):
                value = str(value)
            if column in {"is_superuser", "is_staff", "is_active"} and isinstance(value, bool):
                value = "t" if value else "f"
            if value is None and column != "last_login" or value is not None and not isinstance(value, str):
                raise RehearsalError(f"Current admin user row {row_number}: unsupported field type.")
            if column in {"date_joined", "last_login"} and value is not None:
                try:
                    timestamp = datetime.fromisoformat(value)
                except ValueError:
                    raise RehearsalError(f"Current admin user row {row_number}: invalid account timestamp.") from None
                if timestamp.tzinfo is None:
                    if source_timezone is None:
                        raise RehearsalError(f"Current admin user row {row_number}: a naive account timestamp requires explicit source_timezone.")
                    first = timestamp.replace(tzinfo=source_timezone, fold=0)
                    second = timestamp.replace(tzinfo=source_timezone, fold=1)
                    if first.utcoffset() != second.utcoffset():
                        raise RehearsalError(f"Current admin user row {row_number}: ambiguous or nonexistent local timestamp requires an explicit offset.")
                    value = first.isoformat()
                    timestamps_localized += 1
            converted[column] = value
        users.append(converted)
    if not users:
        raise RehearsalError("The current admin user capture is empty.")
    return users, {
        "captured_at": document.get("captured_at"),
        "source_url": document.get("source_url"),
        "limitations": document.get("limitations", []),
        "user_count": len(users),
        "source_timezones": sorted(source_timezones),
        "naive_timestamps_localized": timestamps_localized,
        "source_group_links_not_mapped": sum(len(row.get("source_groups", [])) for row in document["users"]),
        "source_direct_permission_links_not_mapped": sum(len(row.get("source_user_permissions", [])) for row in document["users"]),
    }


def indexed_ids(rows, column, table):
    result = set()
    for row in rows:
        value = row[column]
        if value is None or value in result:
            raise RehearsalError(f"{table}: empty or duplicate identity.")
        result.add(value)
    return result


def validate_relationships(tables):
    user_ids = indexed_ids(tables["auth_user"], "id", "auth_user")
    storage_ids = indexed_ids(tables.get("dashboard_s3info", []), "id", "dashboard_s3info")
    delivery_ids = indexed_ids(tables["dashboard_delivery"], "id", "dashboard_delivery")
    indexed_ids(tables["dashboard_job"], "job_uuid", "dashboard_job")
    for row in tables["dashboard_delivery"]:
        if row["user_id"] is not None and row["user_id"] not in user_ids:
            raise RehearsalError("A delivery references a user absent from the current admin capture. No identities are invented or references cleared.")
        if row["s3_id"] is not None and row["s3_id"] not in storage_ids:
            raise RehearsalError("A delivery references storage absent from the older snapshot. Obtain the missing source records; no references are cleared.")
    for row in tables["dashboard_job"]:
        if row["delivery_id"] not in delivery_ids:
            raise RehearsalError("A job references a delivery absent from the delivery CSV.")
    for row in tables.get("django_admin_log", []):
        if row["user_id"] not in user_ids:
            raise RehearsalError("An older admin event references a user absent from the current capture.")


def encode_copy(value):
    if value is None:
        return r"\N"
    if not isinstance(value, str) or "\x00" in value:
        raise RehearsalError("Unsupported COPY field type or NUL byte.")
    replacements = {"\\": "\\\\", "\t": r"\t", "\n": r"\n", "\r": r"\r", "\b": r"\b", "\f": r"\f", "\v": r"\v"}
    return "".join(replacements.get(char, f"\\{ord(char):03o}" if ord(char) < 32 else char) for char in value)


def write_interchange(path, tables, columns):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write("-- MIXED AVAILABLE HISTORY: generated import interchange, NOT a current pg_dump.\n")
        stream.write("-- Source originals and provenance are retained separately in this private directory.\n")
        stream.write("SET client_encoding = 'UTF8';\n\n")
        for table in sorted(tables):
            names = columns[table]
            stream.write(f"COPY public.{table} ({', '.join(names)}) FROM stdin;\n")
            for row in tables[table]:
                stream.write("\t".join(encode_copy(row[column]) for column in names) + "\n")
            stream.write("\\.\n\n")
        # Required parser completion sentinel; the preceding comments make the
        # provenance explicit and prevent presenting this as a database backup.
        stream.write("-- PostgreSQL database dump complete\n")
        stream.flush()
        os.fsync(stream.fileno())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--older-dump", type=Path, required=True)
    parser.add_argument("--deliveries-csv", type=Path, required=True)
    parser.add_argument("--jobs-csv", type=Path, required=True)
    parser.add_argument("--current-users-json", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True, help="New private directory; must not exist.")
    arguments = parser.parse_args(argv)
    old_umask = os.umask(0o077)
    run_dir = None
    status = {"kind": "mixed_available_history_import_interchange", "status": "incomplete", "sources": {}}
    return_code = 1
    try:
        run_dir = create_run_directory(arguments.output_dir)
        sources = {
            "older_dump": (arguments.older_dump, "older-snapshot.sql"),
            "deliveries_csv": (arguments.deliveries_csv, "deliveries.csv"),
            "jobs_csv": (arguments.jobs_csv, "jobs.csv"),
            "current_users_json": (arguments.current_users_json, "current-users.json"),
        }
        paths = {}
        for key, (source, basename) in sources.items():
            source = source.expanduser().resolve()
            if not source.is_file():
                raise RehearsalError(f"{key}: supply a regular source file.")
            destination = run_dir / basename
            status["sources"][key] = copy_private(source, destination)
            paths[key] = destination
        older = read_legacy_dump(paths["older_dump"])
        tables = dict(older.tables)
        columns = dict(older.columns)
        tables["auth_user"], status["current_user_capture"] = read_current_users(paths["current_users_json"])
        columns["auth_user"] = USER_COLUMNS
        tables["dashboard_delivery"] = read_table_csv(paths["deliveries_csv"], "dashboard_delivery", DELIVERY_COLUMNS)
        columns["dashboard_delivery"] = DELIVERY_COLUMNS
        tables["dashboard_job"] = read_table_csv(paths["jobs_csv"], "dashboard_job", JOB_COLUMNS)
        columns["dashboard_job"] = JOB_COLUMNS
        status["stale_access_links_cleared"] = {table: len(tables.get(table, [])) for table in CLEAR_LINK_TABLES}
        for table in CLEAR_LINK_TABLES:
            tables[table] = []
            if table not in columns:
                raise RehearsalError("The older snapshot lacks required account link-table metadata.")
        validate_relationships(tables)
        prepared = run_dir / "prepared-import.sql"
        write_interchange(prepared, tables, columns)
        parsed = read_legacy_dump(prepared)
        if parsed.counts != {table: len(rows) for table, rows in tables.items()}:
            raise RehearsalError("Prepared interchange row-count validation failed.")
        status["prepared"] = fingerprint(prepared)
        status["prepared_table_counts"] = parsed.counts
        status["password_policy"] = "All current users have unusable passwords; explicit reset/provisioning is required. No older password hashes are restored."
        status["limitations"] = [
            "Mixed sources are not a coherent current production snapshot or complete backup.",
            "Delivery/job CSV dates and completeness remain as supplied; a current lossy web export is not overlaid.",
            "Empty cells in nullable delivery/job CSV columns are interpreted as SQL NULL; other empty text remains empty.",
            "Storage locations and admin events come from the older SQL snapshot; current storage/jobs may be absent.",
            "Current source groups/direct permissions are archived in JSON but not interpreted as current product access.",
            "Older sessions/API secrets/migration history remain source-only and are omitted by the importer.",
            "Delivery archives, QC reports, verified publication receipts and product specifications are not reconstructed.",
        ]
        for key, (original, _) in sources.items():
            if fingerprint(original.expanduser().resolve()) != status["sources"][key] or fingerprint(paths[key]) != status["sources"][key]:
                raise RehearsalError("A source changed during preparation.")
        status["status"] = "prepared"
        status["original_sources_unchanged"] = True
        print(f"Private prepared interchange: {prepared}")
        print("Mixed available history; not a complete current production backup.")
        print("Counts: " + json.dumps({key: len(tables[key]) for key in ("auth_user", "dashboard_delivery", "dashboard_job", "dashboard_s3info")}, sort_keys=True))
        print("All current passwords are unusable; provision/reset target accounts before login.")
        return_code = 0
    except (RehearsalError, OSError, ValueError, KeyError, TypeError):
        error = sys.exc_info()[1]
        message = str(error) if isinstance(error, RehearsalError) else "Source preparation failed. Check source formats and permissions; no database was touched."
        status["error"] = message
        print(message, file=sys.stderr)
    finally:
        if run_dir is not None:
            try:
                write_json(run_dir / "source-preparation-manifest.json", status)
            except OSError:
                print("The preparation manifest could not be written.", file=sys.stderr)
                return_code = 1
        os.umask(old_umask)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
