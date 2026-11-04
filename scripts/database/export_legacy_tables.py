import argparse
import csv
import os
import subprocess
import uuid
from io import StringIO
from pathlib import Path

from kubectl_files import SUBMISSION_FOLDER, copy_files, existing_files, find_pod, plain_name, remote_lines


# Instructions: This script exports specified PostgreSQL tables from QC Tool production pod to CSV files.
# It can also copy the files of the deliveries and jobs (ZIP files, job results) to the local disk.
# Prerequisities:
# - kubectl installed and configured to access the Kubernetes cluster
# - Access to the QC Tool production pod


# ================= CONFIGURATION =================
NAMESPACE = "qc-tool"
POD_NAME = "database-postgres-ss-0"
DB_USER = "qc_user"       # Replace with your DB user if different
DB_NAME = "qc_tool"         # Replace with your DB name if different

TABLES = [
    "dashboard_job",
    "dashboard_delivery",
    "dashboard_s3info",
    "auth_user",
]

# The pod with the incoming and work directories mounted (the QC Tool frontend),
# in the same namespace. Empty name: first running pod with the prefix.
FILES_POD_NAME = os.getenv("K8S_FILES_POD_NAME", "")
FILES_POD_PREFIX = os.getenv("K8S_FILES_POD_PREFIX", "qc-tool-copernicus-qc-tool-frontend")
# Shell expressions evaluated in that pod; they follow its INCOMING_DIR and WORK_DIR.
INCOMING_ROOT = "${INCOMING_DIR:-/mnt/qc_tool_incoming/incoming}"
WORK_ROOT = "${WORK_DIR:-/mnt/qc_tool_work/work}"
# Submitted deliveries: <root>/<product_ident>/<reference_year>/<date>-<name>-<job uuid>.d
SUBMISSION_ROOT = "${SUBMISSION_DIR:-/mnt/qc_tool_submission/submission}"
# =================================================


def psql_copy(copy_sql):
    cmd = [
        "kubectl", "exec", "-i",
        "-n", NAMESPACE,
        POD_NAME,
        "--",
        "psql",
        "-q",                     # Quiet mode (suppresses extra messaging)
        "-U", DB_USER,
        "-d", DB_NAME,
        "-c", copy_sql
    ]
    # Force UTF-8 decoding and handle non-printable characters gracefully
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True
    ).stdout


def export_table_to_csv(table_name):
    print(f"Exporting table: {table_name}...")

    copy_sql = f"COPY (SELECT * FROM {table_name}) TO STDOUT WITH CSV HEADER;"

    try:
        output = psql_copy(copy_sql)

        output_filename = f"{table_name}.csv"
        with open(output_filename, "w", encoding="utf-8") as f:
            f.write(output)

        print(f" Successfully exported {table_name} -> {output_filename}")

    except subprocess.CalledProcessError as e:
        print(f" Error exporting {table_name}:")
        print(e.stderr)


def query_rows(select_sql):
    try:
        return list(csv.reader(StringIO(psql_copy(f"COPY ({select_sql}) TO STDOUT WITH CSV;"))))
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"Error querying the database:\n{e.stderr}")


def since_clause(column, months, keyword="WHERE"):
    # months is an int (validated by argparse), never user text.
    return f" {keyword} {column} >= now() - make_interval(months => {int(months)})" if months else ""


def download_delivery_files(destination, months, files_pod):
    """The ZIP of each delivery: <incoming>/<username>/<filename>."""
    print("\nCopying the delivery files...", flush=True)
    rows = query_rows(
        "SELECT u.username, d.filename FROM dashboard_delivery d JOIN auth_user u ON u.id = d.user_id "
        + since_clause("d.date_uploaded", months).strip() + " ORDER BY d.id"
    )
    names = []
    for username, filename in rows:
        if plain_name(username) and plain_name(filename):
            names.append(f"{username}/{filename}")
        else:
            print(f"  skipped (unsafe name): {username}/{filename}")
    present = existing_files(NAMESPACE, files_pod, INCOMING_ROOT, names)
    print(f"{len(present)} of {len(names)} delivery files exist.", flush=True)
    if present:
        copy_files(NAMESPACE, files_pod, INCOMING_ROOT, present, destination / "incoming")


def download_job_files(destination, months, files_pod):
    """Per job: the files directly in <work>/job_<uuid hex>/ and <work>/job.<uuid>.stdout."""
    print("\nCopying the job files...", flush=True)
    rows = query_rows("SELECT job_uuid FROM dashboard_job" + since_clause("date_created", months) + " ORDER BY date_created")
    job_uuids = [uuid.UUID(job_uuid) for (job_uuid,) in rows]
    present = existing_files(NAMESPACE, files_pod, WORK_ROOT, [f"job_{job.hex}" for job in job_uuids],
                             job_directories=True)
    present += existing_files(NAMESPACE, files_pod, WORK_ROOT, [f"job.{job}.stdout" for job in job_uuids])
    print(f"{len(present)} job files found for {len(job_uuids)} jobs.", flush=True)
    if present:
        copy_files(NAMESPACE, files_pod, WORK_ROOT, present, destination / "work")


def download_submission_files(destination, months, files_pod):
    """The folder of each submitted delivery: <submission>/<product_ident>/<year>/<...>-<job uuid>.d.

    The reference year is not in the database, so the folders are listed in the pod
    and matched by product and by the job UUID that ends the folder name.
    """
    print("\nCopying the submission folders...", flush=True)
    rows = query_rows(
        "SELECT d.id, d.product_ident, j.job_uuid FROM dashboard_delivery d "
        "LEFT JOIN dashboard_job j ON j.delivery_id = d.id WHERE d.date_submitted IS NOT NULL"
        + since_clause("d.date_submitted", months, "AND") + " ORDER BY d.id"
    )
    deliveries, wanted = {}, {}
    for delivery_id, product_ident, job_uuid in rows:
        deliveries[delivery_id] = product_ident
        if job_uuid:
            wanted[(product_ident.lower(), str(uuid.UUID(job_uuid)))] = delivery_id

    folders = remote_lines(NAMESPACE, files_pod, SUBMISSION_ROOT,
                           "find . -mindepth 3 -maxdepth 3 -type d -name '*.d' | cut -c3-")
    matched, found = [], set()
    for folder in folders:
        parts = folder.split("/")
        match = SUBMISSION_FOLDER.search(parts[-1]) if len(parts) == 3 else None
        delivery_id = wanted.get((parts[0].lower(), match.group(1))) if match else None
        if delivery_id is not None:
            matched.append(folder)
            found.add(delivery_id)
    print(f"{len(deliveries)} submitted deliveries, {len(folders)} submission folders in the pod, "
          f"{len(matched)} of them match.", flush=True)
    lost = [delivery_id for delivery_id in deliveries if delivery_id not in found]
    for delivery_id in lost[:20]:
        print(f"  no submission folder: delivery {delivery_id} ({deliveries[delivery_id]})")
    if len(lost) > 20:
        print(f"  ... and {len(lost) - 20} more deliveries without a submission folder")
    if not matched:
        return
    names = remote_lines(NAMESPACE, files_pod, SUBMISSION_ROOT,
                         'while IFS= read -r d; do find "$d" -type f; done', matched)
    print(f"{len(names)} files in {len(matched)} folders.", flush=True)
    copy_files(NAMESPACE, files_pod, SUBMISSION_ROOT, names, destination / "submission")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", type=int, metavar="N",
                        help="Limit the file downloads to deliveries uploaded, jobs created and deliveries "
                             "submitted within the last N months. The CSV tables are always exported in full.")
    parser.add_argument("--download-deliveries", action="store_true",
                        help="Also copy the ZIP file of each delivery from the incoming directory to the "
                             "local disk (files that are gone are reported).")
    parser.add_argument("--download-jobs", action="store_true",
                        help="Also copy the files of each job (JSON result, log, report) from its work "
                             "directory to the local disk; not the output subdirectory.")
    parser.add_argument("--download-submissions", action="store_true",
                        help="Also copy the submission folder of each submitted delivery (all its files) "
                             "from the submission directory to the local disk.")
    parser.add_argument("--download-dir", default="legacy_files", metavar="DIR",
                        help="Local directory of the copied files (default: legacy_files): "
                             "incoming/<user>/<zip>, work/job_<uuid>/<file>, work/job.<uuid>.stdout "
                             "and submission/<product>/<year>/<folder>.d/...")
    parser.add_argument("--only-download", action="store_true",
                        help="Do not export the tables, only run the --download-* options.")
    args = parser.parse_args()
    if args.months is not None and args.months < 1:
        parser.error("--months expects a positive number")
    if args.only_download and not (args.download_deliveries or args.download_jobs or args.download_submissions):
        parser.error("--only-download needs --download-deliveries, --download-jobs and/or --download-submissions")

    # Verify kubectl is installed and accessible
    try:
        subprocess.run(["kubectl", "version", "--client"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Error: 'kubectl' command not found. Ensure kubectl is installed and in your PATH.")
        return

    if not args.only_download:
        print("Starting CSV export process...")
        for table in TABLES:
            export_table_to_csv(table)

    if args.download_deliveries or args.download_jobs or args.download_submissions:
        destination = Path(args.download_dir)
        files_pod = find_pod(NAMESPACE, FILES_POD_NAME, FILES_POD_PREFIX)
        print(f"\nCopying files from {NAMESPACE}/{files_pod} to {destination}...", flush=True)
        if args.download_deliveries:
            download_delivery_files(destination, args.months, files_pod)
        if args.download_jobs:
            download_job_files(destination, args.months, files_pod)
        if args.download_submissions:
            download_submission_files(destination, args.months, files_pod)
    print("Done!")


if __name__ == "__main__":
    main()
