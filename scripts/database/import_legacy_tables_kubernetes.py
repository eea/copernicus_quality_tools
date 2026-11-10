import argparse
import os
import shlex
import subprocess
from pathlib import Path

from kubectl_files import (
    SUBMISSION_FOLDER, find_pod, long_path, plain_name, remote_exists, remote_lines, upload_groups,
)


# Instructions: This script runs the legacy import scripts inside the QC Tool
# frontend pod, which has psycopg2, the POSTGRES_* connection variables and
# PRODUCT_DIRS. The scripts and CSV files (from export_legacy_tables.py) are
# copied into a temporary directory of the pod, which is removed afterwards.
# Prerequisities:
# - kubectl installed and configured to access the Kubernetes cluster
# - Access to the QC Tool frontend pod
# - The CSV files in the current directory


# ================= CONFIGURATION =================
NAMESPACE = os.getenv("K8S_NAMESPACE", "qc-tool")
POD_NAME = os.getenv("K8S_POD_NAME", "")  # Empty: first running pod with POD_PREFIX.
POD_PREFIX = os.getenv("K8S_POD_PREFIX", "qc-tool-copernicus-qc-tool-frontend")
REMOTE_DIR = "/tmp/qc_tool_legacy_import"

# Database the scripts import into. The scripts read it as QC_DB_* environment
# variables, which this script sets for them in the pod. An empty value keeps
# the POSTGRES_* variable of the frontend pod (the application's own database).
DB_CONFIG = {
    "dbname": os.getenv("QC_DB_NAME", "qc_tool_staging7"),
    "user": os.getenv("QC_DB_USER", "qc_user"),
    "password": os.getenv("QC_DB_PASSWORD", "qc_password"),
    "host": os.getenv("QC_DB_HOST", ""),
    "port": os.getenv("QC_DB_PORT", "5432"),
}
# =================================================

SCRIPT_DIR = Path(__file__).resolve().parent
DB_ENV_FILE = "db_config.env"

# Steps in dependency order: script and the CSV files it reads.
STEPS = {
    "users": ("import_legacy_users.py", ["auth_user.csv"]),
    "permissions": ("import_legacy_permissions.py", []),
    "deliveries": ("import_legacy_deliveries.py", ["dashboard_s3info.csv", "dashboard_delivery.csv"]),
    "jobs": ("import_legacy_jobs.py", ["dashboard_job.csv"]),
    "delivery-unit-codes": ("guess_legacy_delivery_unit_codes.py", []),
    "job-unit-codes": ("guess_legacy_job_unit_codes.py", []),
    "submissions": ("create_legacy_publication_submissions.py", []),
    "submission-manifests": ("write_legacy_submission_manifests.py", []),
}

# Optional steps run only when named explicitly.
OPTIONAL_STEPS = ["permissions"]

# Steps limited by --months (deliveries by upload date, jobs by creation date).
MONTHS_STEPS = ["deliveries", "jobs"]

# Files uploaded to the pod with --upload-deliveries / --upload-jobs / --upload-submissions:
# (root directory in the pod, local subdirectory). The root is a shell expression
# evaluated in the pod, so it follows its INCOMING_DIR, WORK_DIR and SUBMISSION_DIR.
UPLOADS = {
    "deliveries": ("${INCOMING_DIR:-/mnt/qc_tool_incoming/incoming}", "incoming"),
    "jobs": ("${WORK_DIR:-/mnt/qc_tool_work/work}", "work"),
    "submissions": ("${SUBMISSION_DIR:-/mnt/qc_tool_submission/submission}", "submission"),
}

# Steps limited by --product-ident; the others always process everything.
# Storage sources of the deliveries step are imported in full as well.
PRODUCT_STEPS = ["deliveries", "jobs", "delivery-unit-codes", "job-unit-codes", "submissions",
                 "submission-manifests"]


def kubectl_exec(pod, shell_command, stdin=False):
    cmd = ["kubectl", "exec"]
    if stdin:
        cmd.append("-i")
    return cmd + ["-n", NAMESPACE, pod, "--", "sh", "-c", shell_command]


def upload(pod, path):
    print(f" Uploading {path.name}...", flush=True)
    target = shlex.quote(f"{REMOTE_DIR}/{path.name}")
    subprocess.run(
        kubectl_exec(pod, f"cat > {target}", stdin=True),
        input=path.read_bytes(), check=True,
    )


def upload_db_config(pod):
    """Store DB_CONFIG as a shell file in the pod; the directory is removed at the end.

    A file keeps the password out of command lines, which other processes can read.
    """
    lines = [f"export QC_DB_{key.upper()}={shlex.quote(value)}\n" for key, value in DB_CONFIG.items() if value]
    target = shlex.quote(f"{REMOTE_DIR}/{DB_ENV_FILE}")
    subprocess.run(
        kubectl_exec(pod, f"umask 077 && cat > {target}", stdin=True),
        input="".join(lines).encode(), check=True,
    )


def python_command(script, *options):
    """Shell command running a script in the pod with the DB_CONFIG variables."""
    return " ".join([f"cd {REMOTE_DIR} && . ./{DB_ENV_FILE} && python3 -u {script}", *map(shlex.quote, options)])


def upload_files(pod, kind, local_dir, product_idents, months, dry_run):
    """Upload the local files of the imported deliveries, jobs or submissions that the pod does not have.

    The database of the pod says which items exist (--months and --product-ident
    apply). A delivery is skipped when its ZIP exists in the incoming directory of
    the pod, a job when its job_<uuid> folder or its job.<uuid>.stdout log exists in
    the work directory. A submission folder keeps its place,
    <product>/<year>/<date>-<name>-<job uuid>.d below the submission directory, and is
    skipped when the pod has a folder of that job UUID in any product or year. The
    files of an item are uploaded together.
    """
    root, subdirectory = UPLOADS[kind]
    shown = local_dir / subdirectory
    local_root = long_path(shown)
    options = ["--months", str(months)] if months else []
    for ident in product_idents or []:
        options += ["--product-ident", ident]
    print(f"\n=== upload {kind} ===", flush=True)
    listing = subprocess.run(
        kubectl_exec(pod, python_command("list_legacy_files.py", kind, *options)),
        stdout=subprocess.PIPE, text=True,
    )
    if listing.returncode != 0:
        raise SystemExit(f"Error: listing the {kind} failed with exit code {listing.returncode}.")
    items = listing.stdout.splitlines()

    folders = {}
    if kind == "submissions" and local_root.is_dir():
        # <product>/<year>/<date>-<name>-<job uuid>.d, found by the job UUID.
        for folder in local_root.glob("*/*/*.d"):
            match = SUBMISSION_FOLDER.search(folder.name)
            if match and folder.is_dir():
                folders[match.group(1)] = folder

    # entries: (names of which none may exist in the pod yet, files to upload together).
    # A file is (name relative to the local directory, name relative to the pod directory).
    entries, not_local = [], 0
    for item in items:
        if kind == "deliveries":
            keys = [item]
            files = [(item, item)] if (local_root / item).is_file() else []
        elif kind == "jobs":
            job_dir, stdout = f"job_{item.replace('-', '')}", f"job.{item}.stdout"
            folder = local_root / job_dir
            names = sorted(path.name for path in folder.iterdir() if path.is_file()) if folder.is_dir() else []
            keys = [job_dir, stdout]
            files = [(f"{job_dir}/{name}",) * 2 for name in names if plain_name(name)]
            files += [(stdout, stdout)] if (local_root / stdout).is_file() else []
        else:
            keys = [item]
            folder = folders.get(item)
            files = [(path.relative_to(local_root).as_posix(),) * 2
                     for path in sorted(folder.rglob("*")) if path.is_file()] if folder else []
        if files:
            entries.append((keys, files))
        else:
            not_local += 1
    if kind == "submissions":
        # The same listing as the export: <product>/<year>/<name>.d, found by the job UUID.
        in_pod = remote_lines(NAMESPACE, pod, root, "find . -mindepth 3 -maxdepth 3 -type d -name '*.d' | cut -c3-")
        existing = {match.group(1) for name in in_pod if (match := SUBMISSION_FOLDER.search(name))}
    else:
        existing = remote_exists(NAMESPACE, pod, root, [key for keys, _ in entries for key in keys])
    groups = [files for keys, files in entries if not existing.intersection(keys)]
    print(f"{len(items)} {kind} in the database: {len(entries) - len(groups)} already in the pod, "
          f"{not_local} not in {shown}, {len(groups)} to upload "
          f"({sum((local_root / local).stat().st_size for files in groups for local, _ in files) / 1e6:.0f} MB).", flush=True)
    if dry_run or not groups:
        print("Nothing uploaded." if groups else "No files to upload.", flush=True)
        return
    upload_groups(NAMESPACE, pod, root, shown, groups)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("steps", nargs="*", metavar="step",
                        help=f"Steps to run: {', '.join(STEPS)} (default: all except "
                             f"{', '.join(OPTIONAL_STEPS)}, in this order).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Each script rolls back its changes. Later steps then do not see "
                             "the data of earlier ones, so use it on an already imported database.")
    parser.add_argument("--product-ident", action="append", dest="product_idents",
                        help="Only import and process deliveries and jobs of this product, e.g. clc2024 "
                             "(case-insensitive; repeatable). Default steps are then all except users.")
    parser.add_argument("--months", type=int, metavar="N",
                        help="Only import deliveries uploaded and jobs created within the last N months, "
                             "and only upload their files and the folders of submissions requested in "
                             "that time (the other steps are not limited by it).")
    parser.add_argument("--upload-deliveries", action="store_true",
                        help="Also upload the ZIP file of each imported delivery from the local directory "
                             "to the incoming directory of the pod, unless it exists there already.")
    parser.add_argument("--upload-jobs", action="store_true",
                        help="Also upload the files of each imported job from the local directory to the "
                             "work directory of the pod (the job_<uuid> folder and job.<uuid>.stdout), "
                             "unless they exist there already.")
    parser.add_argument("--upload-submissions", action="store_true",
                        help="Also upload the submission folder of each legacy submission record (the "
                             "'submissions' step creates them) from the local directory to the same "
                             "<product>/<year>/<folder>.d below the submission directory of the pod, unless "
                             "the pod has a folder of that job UUID already. Run the 'submissions' step first. "
                             "Afterwards the placeholder keys of the legacy submissions are replaced by "
                             "these folders.")
    parser.add_argument("--upload-dir", default="legacy_files", metavar="DIR",
                        help="Local directory of the files to upload (default: legacy_files, as written "
                             "by export_legacy_tables.py): incoming/<user>/<zip>, work/job_<uuid>/<file>, "
                             "work/job.<uuid>.stdout and submission/<product>/<year>/<folder>.d/...")
    parser.add_argument("--only-upload", action="store_true",
                        help="Run no import step, only the --upload-* options.")
    parser.add_argument("--auto-approve", nargs="?", const="yes", default="no", metavar="yes|no",
                        help="Approve the newest legacy submission per unit where possible "
                             "(default: no, submissions await approval review).")
    args = parser.parse_args()
    if args.auto_approve.strip().lower() not in ("yes", "y", "true", "1", "no", "n", "false", "0"):
        parser.error("--auto-approve expects yes or no")
    if args.months is not None and args.months < 1:
        parser.error("--months expects a positive number")
    if args.only_upload and not (args.upload_deliveries or args.upload_jobs or args.upload_submissions):
        parser.error("--only-upload needs --upload-deliveries, --upload-jobs and/or --upload-submissions")
    unknown = [name for name in args.steps if name not in STEPS]
    if unknown:
        parser.error(f"unknown steps: {', '.join(unknown)}")
    steps = args.steps or (
        PRODUCT_STEPS if args.product_idents else [name for name in STEPS if name not in OPTIONAL_STEPS]
    )
    if args.only_upload:
        steps = []

    # Verify kubectl is installed and accessible
    try:
        subprocess.run(["kubectl", "version", "--client"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Error: 'kubectl' command not found. Ensure kubectl is installed and in your PATH.")
        return

    csv_files = [Path(name) for step in steps for name in STEPS[step][1]]
    missing = [str(path) for path in csv_files if not path.is_file()]
    if missing:
        raise SystemExit(f"Error: missing CSV files in the current directory: {', '.join(missing)}")

    pod = find_pod(NAMESPACE, POD_NAME, POD_PREFIX)
    print(f"Running {', '.join(steps)} in {NAMESPACE}/{pod}...", flush=True)
    if args.product_idents:
        print(f"Products: {', '.join(args.product_idents)}", flush=True)
    if args.months:
        print(f"Deliveries and jobs of the last {args.months} months", flush=True)

    subprocess.run(kubectl_exec(pod, f"rm -rf {REMOTE_DIR} && mkdir -p {REMOTE_DIR}"), check=True)
    try:
        upload_db_config(pod)
        for path in sorted(SCRIPT_DIR.glob("*legacy*.py")):
            if path.name != Path(__file__).name:
                upload(pod, path)
        for path in csv_files:
            upload(pod, path)

        for step in steps:
            script = STEPS[step][0]
            options = ["--dry-run"] if args.dry_run else []
            if step == "submissions":
                options += ["--auto-approve", args.auto_approve]
            if step in PRODUCT_STEPS:
                for ident in args.product_idents or []:
                    options += ["--product-ident", ident]
            if step in MONTHS_STEPS and args.months:
                options += ["--months", str(args.months)]
            print(f"\n=== {step}: {script} ===", flush=True)
            result = subprocess.run(kubectl_exec(pod, python_command(script, *options)))
            if result.returncode != 0:
                raise SystemExit(f"Error: step '{step}' failed with exit code {result.returncode}.")

        local_dir = Path(args.upload_dir)
        for kind, wanted in (("deliveries", args.upload_deliveries), ("jobs", args.upload_jobs),
                             ("submissions", args.upload_submissions)):
            if wanted:
                upload_files(pod, kind, local_dir, args.product_idents, args.months, args.dry_run)
            if wanted and kind == "submissions":
                # The folders are in the pod now: point the legacy submissions at them.
                options = ["--link-folders"] + (["--dry-run"] if args.dry_run else [])
                for ident in args.product_idents or []:
                    options += ["--product-ident", ident]
                print("\n=== link submissions to their folders ===", flush=True)
                result = subprocess.run(kubectl_exec(
                    pod, python_command("create_legacy_publication_submissions.py", *options)))
                if result.returncode != 0:
                    raise SystemExit(f"Error: linking the submission folders failed with exit code {result.returncode}.")
                if "submission-manifests" not in steps:
                    # The page of a submission needs its manifest; write it for the folders just linked.
                    options = (["--dry-run"] if args.dry_run else [])
                    for ident in args.product_idents or []:
                        options += ["--product-ident", ident]
                    print("\n=== write submission manifests ===", flush=True)
                    result = subprocess.run(kubectl_exec(
                        pod, python_command("write_legacy_submission_manifests.py", *options)))
                    if result.returncode != 0:
                        raise SystemExit(f"Error: writing the submission manifests failed with exit code {result.returncode}.")
    finally:
        # The CSV files contain password hashes and storage credentials, and
        # the db config file the database password.
        subprocess.run(kubectl_exec(pod, f"rm -rf {REMOTE_DIR}"))
        print(f"\nRemoved {REMOTE_DIR} from the pod.")
    print("Done!")


if __name__ == "__main__":
    main()
