#!/usr/bin/env python3
"""Compare browser delivery exports with original legacy CSVs, without writes.

Only aggregate diagnostics and source fingerprints are printed. XLSX exports
omit user IDs, job finish times, skipped checks and historical jobs; they are
verification evidence, not replacements for the original migration sources.
"""

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile
import xml.etree.ElementTree as ET


NS = {
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
EXPORT_COLUMNS = (
    "id", "filename", "username", "date_uploaded", "size_bytes",
    "product_ident", "product_description", "date_submitted", "is_deleted",
    "s3_id", "aoi_code", "last_job_uuid", "last_job_worker_url",
    "date_created", "date_started", "last_job_status", "user_country", "type",
)
DELIVERY_FIELDS = (
    "filename", "product_ident", "product_description", "size_bytes",
    "s3_id", "aoi_code",
)
JOB_FIELDS = {
    "last_job_worker_url": "worker_url", "last_job_status": "job_status",
}


class ReconciliationError(ValueError):
    """An operator-safe error without source values."""


def fingerprint(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return {"sha256": digest.hexdigest(), "size_bytes": path.stat().st_size}


def read_csv(path, key, required):
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not required.issubset(reader.fieldnames or ()):
            raise ReconciliationError("Original CSV columns are incomplete.")
        rows = {}
        for row in reader:
            if not row.get(key) or row[key] in rows or None in row:
                raise ReconciliationError("Original CSV contains missing or duplicate keys, or malformed rows.")
            rows[row[key]] = row
    return rows


def read_xlsx(path):
    """Read scalar delivery cells without evaluating formulas or links."""
    with ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        properties = workbook.find("s:workbookPr", NS)
        if properties is not None and properties.get("date1904") in {"1", "true"}:
            raise ReconciliationError("The export uses an unsupported date epoch.")
        relationships = {
            item.get("Id"): item.get("Target")
            for item in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        }
        sheets = workbook.findall("s:sheets/s:sheet", NS)
        if len(sheets) != 1 or sheets[0].get("name") != "Deliveries":
            raise ReconciliationError("Expected exactly one Deliveries worksheet.")
        target = relationships[sheets[0].get("{" + NS["r"] + "}id")]
        sheet_path = target.lstrip("/") if target.startswith("/") else "xl/" + target
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = [
                "".join(item.itertext())
                for item in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("s:si", NS)
            ]

        def value(cell):
            if cell.find("s:f", NS) is not None:
                raise ReconciliationError("The delivery export unexpectedly contains formulas.")
            scalar = cell.find("s:v", NS)
            if cell.get("t") == "s":
                return strings[int(scalar.text)]
            if cell.get("t") == "inlineStr":
                return "".join(cell.find("s:is", NS).itertext())
            return scalar.text or "" if scalar is not None else ""

        rows = ET.fromstring(archive.read(sheet_path)).findall("s:sheetData/s:row", NS)
        if not rows:
            raise ReconciliationError("The delivery export has no header.")
        columns = {cell.get("r").rstrip("0123456789"): value(cell) for cell in rows[0]}
        if tuple(columns.values()) != EXPORT_COLUMNS:
            raise ReconciliationError("The delivery export headers differ from the supported production schema.")
        return [
            {columns[cell.get("r").rstrip("0123456789")]: value(cell) for cell in row}
            for row in rows[1:]
        ]


def date_matches(exported, original):
    if not exported or not original:
        return not exported and not original
    # Excel stores local wall-clock timestamps without the source UTC offset.
    excel = datetime(1899, 12, 30) + timedelta(days=float(exported))
    source = datetime.fromisoformat(original).replace(tzinfo=None)
    return abs((excel - source).total_seconds()) <= 0.000002


def reconcile(deliveries, jobs, exports, *, expected_active_count=None, users=None):
    job_groups = defaultdict(list)
    for job in jobs.values():
        job_groups[job["delivery_id"]].append(job)
    latest = {
        key: max(group, key=lambda job: datetime.fromisoformat(job["date_created"]))
        for key, group in job_groups.items()
    }
    counts = Counter(row.get("id", "") for row in exports)
    if "" in counts:
        raise ReconciliationError("The delivery exports contain missing identifiers.")
    live = {row["id"]: row for row in exports}
    active_ids = {key for key, row in deliveries.items() if row["is_deleted"] == "f"}
    changed = Counter()
    changed_rows = 0
    ownership_unresolved = 0
    new_ids = set(live) - set(deliveries)
    new_job_rows = 0
    for key, row in live.items():
        if row.get("last_job_uuid") and row["last_job_uuid"] not in jobs:
            new_job_rows += 1
        if key in new_ids:
            continue
        original = deliveries[key]
        differences = [field for field in DELIVERY_FIELDS if row.get(field, "") != original[field]]
        for field in ("date_uploaded", "date_submitted"):
            if not date_matches(row.get(field, ""), original[field]):
                differences.append(field)
        if row.get("is_deleted") not in {"0", "1"}:
            raise ReconciliationError("The export contains unsupported boolean values.")
        if (row["is_deleted"] == "1") != (original["is_deleted"] == "t"):
            differences.append("is_deleted")
        user = users.get(original["user_id"]) if users is not None else None
        if user is None:
            ownership_unresolved += 1
        elif row.get("username", "") != user["username"]:
            differences.append("username")
        job = latest.get(key)
        if row.get("last_job_uuid", "") != (job["job_uuid"] if job else ""):
            differences.append("last_job_uuid")
        if job:
            for exported, source in JOB_FIELDS.items():
                if row.get(exported, "") != job[source]:
                    differences.append(exported)
            for field in ("date_created", "date_started"):
                if not date_matches(row.get(field, ""), job[field]):
                    differences.append(field)
        elif any(row.get(field) for field in (*JOB_FIELDS, "date_created", "date_started")):
            differences.append("unexpected_job_fields")
        if differences:
            changed_rows += 1
            changed.update(differences)
    duplicates = sum(number - 1 for number in counts.values())
    scope_complete = (
        expected_active_count is not None
        and len(live) == expected_active_count
        and duplicates == 0
        and all(row.get("is_deleted") == "0" for row in exports)
    )
    return {
        "original_deliveries": len(deliveries), "original_jobs": len(jobs),
        "original_active_deliveries": len(active_ids),
        "exported_rows": len(exports), "unique_exported_deliveries": len(live),
        "duplicate_exported_rows": duplicates,
        "declared_live_active_count": expected_active_count,
        "declared_scope_count_matches": scope_complete,
        "new_delivery_ids_without_full_original_metadata": len(new_ids),
        "exported_jobs_absent_from_original_history": new_job_rows,
        "original_active_ids_absent_from_exports": len(active_ids - set(live)),
        "changed_overlapping_delivery_rows": changed_rows,
        "changed_field_counts": dict(sorted(changed.items())),
        "overlapping_owner_references_unresolved": ownership_unresolved,
        "submitted_exported_rows": sum(bool(row.get("date_submitted")) for row in live.values()),
        "exported_last_job_status_counts": dict(Counter(row.get("last_job_status", "") for row in live.values())),
        "complete_reconciliation": bool(
            scope_complete and not new_ids and not new_job_rows and not changed_rows
            and not ownership_unresolved and not (active_ids - set(live))
        ),
        "limitations": [
            "Browser exports omit user_id, date_finished, skip_steps and older jobs; they cannot reconstruct new history.",
            "Excel timestamps retain local wall-clock values, but omit timezone offsets.",
            "An absent active ID alone does not prove that its delivery was deleted.",
            "The declared production count must be independently observed with the same complete nondeleted scope.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delivery-csv", type=Path, required=True)
    parser.add_argument("--job-csv", type=Path, required=True)
    parser.add_argument("--legacy-dump", type=Path, help="Optional full backup for owner-ID-to-username verification.")
    parser.add_argument("--expected-active-count", type=int)
    parser.add_argument("exports", type=Path, nargs="+")
    args = parser.parse_args()
    paths = [args.delivery_csv, args.job_csv, *args.exports]
    if args.legacy_dump:
        paths.append(args.legacy_dump)
    before = {str(path): fingerprint(path) for path in paths}
    deliveries = read_csv(args.delivery_csv, "id", set(DELIVERY_FIELDS) | {"id", "user_id", "is_deleted", "date_uploaded", "date_submitted"})
    jobs = read_csv(args.job_csv, "job_uuid", {"job_uuid", "delivery_id", "date_created", "date_started", "job_status", "worker_url"})
    users = None
    if args.legacy_dump:
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
        from qc_tool.database.legacy.dump import read_legacy_dump
        source = read_legacy_dump(args.legacy_dump)
        users = {row["id"]: row for row in source.tables.get("auth_user", ())}
    exports = [row for path in args.exports for row in read_xlsx(path)]
    report = reconcile(deliveries, jobs, exports, expected_active_count=args.expected_active_count, users=users)
    after = {str(path): fingerprint(path) for path in paths}
    if before != after:
        raise ReconciliationError("A source changed while being read. Capture stable snapshots before reconciling.")
    report["sources"] = before
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["complete_reconciliation"] else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReconciliationError as error:
        print(f"Reconciliation failed: {error}", file=sys.stderr)
        raise SystemExit(1)
    except Exception:
        # Do not expose parsed usernames, worker locations or source values.
        print("Reconciliation failed while reading or validating source data.", file=sys.stderr)
        raise SystemExit(1)
