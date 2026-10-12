#!/usr/bin/env python3
"""Run genuine legacy ZIPs through an already isolated current-source worker.

This never uploads, submits, modifies specifications, or contacts a frontend.
It retains real worker reports. Use --current-checks to execute every configured
current check, with archived comparison reported as supplementary evidence.
These archived/current diagnostic runs do not establish strict production/v3
parity; that requires paired production-reference and v3 results for identical
inputs, original specifications and the production dependency profile. Only
damaged ZIP inputs are excepted from the requested status-preservation contract.
The worker container must have the evidence incoming and work directories
mounted at /verification/incoming and /verification/work respectively.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import fcntl
import io
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
import zipfile

GIB = 1024**3
PROVENANCE_MODULES = (
    "qc_tool.common", "qc_tool.worker.cmd", "qc_tool.worker.dispatch",
    "qc_tool.raster.inspire", "qc_tool.raster.gap", "qc_tool.vector.overlap",
)
PROTECTED_CHECK_DIRS = ("src/qc_tool/raster", "src/qc_tool/vector")
QC_TERMINAL_STEP_STATUSES = {"ok", "failed", "aborted", "cancelled"}


def path_component(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 500 or value in (".", "..") or "/" in value or "\\" in value or any(ord(char) < 32 for char in value):
        raise ValueError(f"Invalid {label} path component")
    return value


def confined_input(incoming: Path, filename: str) -> Path:
    path_component(filename, "filename")
    root = incoming.resolve()
    path = incoming / filename
    if path.resolve().parent != root:
        raise ValueError("Input filename escapes the isolated incoming directory")
    return path


def verify_module_origins(origins: dict, repo: Path) -> None:
    container_repo = Path("/usr/local/src/copernicus_quality_tools")
    for name in PROVENANCE_MODULES:
        record = origins.get(name)
        expected_relative = Path("src").joinpath(*name.split(".")).with_suffix(".py")
        expected_path = container_repo / expected_relative
        if not record or Path(record["path"]) != expected_path or record["sha256"] != sha256_file(repo / expected_relative):
            raise ValueError(f"Worker imported unexpected source bytes for {name}")


class _FailureMessages(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.stack = []

    def handle_starttag(self, tag, attributes):
        if tag in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "wbr"}:
            return
        classes = dict(attributes).get("class", "").split()
        self.stack.append((tag, "FailureMessage" in classes or bool(self.stack and self.stack[-1][1])))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                self.stack = self.stack[:index]
                break

    def handle_data(self, value):
        if self.stack and self.stack[-1][1] and value.strip():
            self.parts.append(value.strip())


def inspire_infrastructure_errors(report_html: str) -> list[str]:
    """Separate an ETF system failure from an actual metadata rejection."""
    parser = _FailureMessages()
    parser.feed(report_html)
    return [part[:1500] for part in parser.parts if part.startswith("System error in the Executable Test Suite.")]


def external_runtime_gap(messages: str) -> bool:
    messages = messages.lower()
    missing = any(word in messages for word in ("not available", "not found", "does not exist"))
    return (
        (missing and ("boundary" in messages or "mask" in messages))
        or ("service" in messages and any(word in messages for word in ("has not responded", "does not have any test suites", "unavailable")))
        or "unable to validate metadata" in messages
        or "validation service is busy" in messages
        or ("not available" in messages and "inspire" in messages and ("report " in messages or "log file " in messages))
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            digest.update(block)
    return digest.hexdigest()


def source_snapshot(repo: Path) -> dict:
    """Record the actual mounted bytes, including uncommitted fixes."""
    files = []
    for parent in (repo / "src/qc_tool", repo / "product_definitions", repo / "docker"):
        for path in sorted(parent.rglob("*")):
            if (
                path.is_file()
                and "backups" not in path.parts
                and "__pycache__" not in path.parts
                and (path.suffix in (".py", ".json", ".conf", ".sh") or path.name.startswith("Dockerfile"))
            ):
                files.append({"path": str(path.relative_to(repo)), "sha256": sha256_file(path)})
    fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return {
        "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
        "status": subprocess.check_output(["git", "status", "--short"], cwd=repo, text=True),
        "fingerprint": fingerprint,
        "files": files,
    }


def protected_checks_snapshot(repo: Path) -> dict:
    """Require the tracked check bytes from HEAD and reject extra source files."""
    tree = subprocess.check_output(["git", "ls-tree", "-r", "-z", "HEAD", "--", *PROTECTED_CHECK_DIRS], cwd=repo)
    entries = []
    for entry in tree.split(b"\0"):
        if entry:
            metadata, name = entry.split(b"\t", 1)
            mode, kind, blob = metadata.decode().split()
            if kind != "blob" or mode not in ("100644", "100755"):
                raise ValueError("Protected check tree contains an unsupported Git entry")
            entries.append((name.decode(), blob))
    if not entries:
        raise ValueError("Protected check folders have no tracked HEAD files")
    blobs = io.BytesIO(subprocess.check_output(
        ["git", "cat-file", "--batch"], cwd=repo,
        input="".join(blob + "\n" for _, blob in entries).encode(),
    ))
    files = []
    changed = []
    for name, blob in entries:
        returned_blob, kind, size = blobs.readline().decode().split()
        if returned_blob != blob or kind != "blob":
            raise ValueError("Could not read protected HEAD bytes")
        expected_hash = hashlib.sha256(blobs.read(int(size))).hexdigest()
        if blobs.read(1) != b"\n":
            raise ValueError("Invalid protected HEAD blob response")
        path = repo / name
        actual_hash = sha256_file(path) if path.is_file() and not path.is_symlink() else None
        files.append({"path": name, "sha256": actual_hash, "head_sha256": expected_hash})
        if actual_hash != expected_hash:
            changed.append(name)
    tracked = {name for name, _ in entries}
    for directory in PROTECTED_CHECK_DIRS:
        for path in (repo / directory).rglob("*"):
            if (path.is_file() or path.is_symlink()) and "__pycache__" not in path.parts:
                name = str(path.relative_to(repo))
                if name not in tracked:
                    changed.append(name)
    if changed:
        raise ValueError("Protected check folders differ from HEAD: " + ", ".join(sorted(changed)))
    return {"revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
            "fingerprint": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
            "files": files, "all_tracked_bytes_match_head": True, "excluded_generated_directories": ["__pycache__"]}


def selected_legacy_skips(baseline: dict | None, current_checks: bool) -> list[int]:
    if current_checks:
        return []
    return [number for number, step in enumerate((baseline or {}).get("steps") or [], 1) if step.get("status") == "skipped"]


def current_check_outcome(result: dict | None, passes_all_checks: bool, infrastructure_gap: bool) -> str:
    if infrastructure_gap or not result or result.get("error_message") or result.get("status") not in ("ok", "failed", "partial"):
        return "inconclusive"
    if passes_all_checks:
        return "passed"
    return result["status"] if result["status"] != "ok" else "inconclusive"


def batch_succeeded(summary: dict) -> bool:
    cases = summary["cases"]
    complete = len(cases) == summary["chosen_case_count"] and bool(cases)
    if summary.get("current_checks"):
        accepted = all(case["passes_all_checks"] and case["current_check_outcome"] == "passed" for case in cases)
    else:
        accepted = all(case["parity_matches"] is True for case in cases)
    return complete and summary["source_unchanged_during_run"] and not summary.get("stopped_reason") and accepted


def inspect_archive_space(path: Path, scratch: Path, factor: float, reserve_bytes: int) -> dict:
    """Use archive declarations to guard disk space without extracting inputs."""
    metadata_readable = True
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            unpacked_bytes = sum(member.file_size for member in members)
    except zipfile.BadZipFile:
        # The genuine worker ZIP check must reject this negative input. Do not
        # crash the comparison runner before that check executes.
        members = []
        unpacked_bytes = 0
        metadata_readable = False
    free_bytes = shutil.disk_usage(scratch).free
    required_bytes = int(unpacked_bytes * factor) + reserve_bytes
    return {
        "member_count": len(members),
        "archive_metadata_readable": metadata_readable,
        "declared_uncompressed_bytes": unpacked_bytes,
        "scratch_free_bytes": free_bytes,
        "scratch_required_bytes": required_bytes,
        "scratch_factor": factor,
        "reserve_bytes": reserve_bytes,
        "space_available": free_bytes >= required_bytes,
    }


def assess_result(result: dict, recipe: dict, expected_hash: str) -> dict:
    expected = [step["check_ident"] for step in recipe["steps"]]
    steps = result.get("steps", [])
    actual = [step.get("check_ident") for step in steps]
    statuses = [step.get("status") for step in steps]
    skipped = any(status == "skipped" for status in statuses)
    complete = bool(expected) and actual == expected and all(status in QC_TERMINAL_STEP_STATUSES for status in statuses)
    hash_matches = result.get("hash") == expected_hash
    passed = (
        result.get("status") == "ok"
        and not result.get("error_message")
        and complete
        and not skipped
        and all(status == "ok" for status in statuses)
        and hash_matches
    )
    return {
        "status": result.get("status"),
        "expected_step_count": len(expected),
        "configured_step_entry_count": len(steps),
        "executed_step_count": sum(status in QC_TERMINAL_STEP_STATUSES for status in statuses),
        "all_configured_steps_completed": complete,
        "any_step_skipped": skipped,
        "input_hash_matches_worker": hash_matches,
        "passes_all_checks": passed,
        "unsuccessful_steps": [step for step in steps if step.get("status") != "ok"],
        "error_message": result.get("error_message"),
    }


def assess_parity(baseline: dict | None, result: dict | None, input_hash: str, *, infrastructure_error: bool = False, candidate_is_complete: bool = True) -> dict:
    """Compare observed acceptance, without counting infrastructure errors as rejection."""
    inconclusive = {"parity_outcome": "inconclusive", "parity_matches": None}
    if not baseline or not baseline.get("hash") or baseline.get("hash") != input_hash:
        return {**inconclusive, "parity_reason": "Archived baseline missing or historical input SHA256 does not match."}
    if baseline.get("status") not in ("ok", "failed", "partial") or baseline.get("error_message"):
        return {**inconclusive, "parity_reason": "Historical outcome is an infrastructure/error state, not a comparable QC decision."}
    if any(external_runtime_gap(str(message)) for step in (baseline.get("steps") or []) for message in (step.get("messages") or [])):
        return {**inconclusive, "parity_reason": "Historical failure contains a recognizable service, report, boundary, or mask infrastructure gap."}
    if infrastructure_error or not result or result.get("status") not in ("ok", "failed", "partial") or result.get("error_message"):
        return {**inconclusive, "parity_reason": "Candidate runtime failed, timed out, lacks a result, or has an infrastructure gap."}
    if result.get("hash") != input_hash:
        return {**inconclusive, "parity_reason": "Candidate worker input SHA256 does not match."}
    if result["status"] == "ok" and not candidate_is_complete:
        return {**inconclusive, "parity_reason": "Candidate acceptance lacks complete configured checks and report evidence."}
    old_steps = baseline.get("steps") or []
    new_steps = result.get("steps") or []
    deltas = []
    for number in range(max(len(old_steps), len(new_steps))):
        old = old_steps[number] if number < len(old_steps) else {}
        new = new_steps[number] if number < len(new_steps) else {}
        if (old.get("check_ident"), old.get("status")) != (new.get("check_ident"), new.get("status")):
            deltas.append({"step": number + 1, "legacy_check": old.get("check_ident"), "candidate_check": new.get("check_ident"), "legacy_status": old.get("status"), "candidate_status": new.get("status")})
    matched = (baseline["status"] == "ok") == (result["status"] == "ok")
    return {
        "parity_outcome": "matched_pass" if matched and baseline["status"] == "ok" else "matched_nonpass" if matched else "mismatch",
        "parity_matches": matched,
        "legacy_status": baseline["status"], "candidate_status": result["status"],
        "legacy_qc_tool_version": baseline.get("qc_tool_version"),
        "candidate_qc_tool_version": result.get("qc_tool_version"),
        "step_status_deltas": deltas,
        "legacy_skipped_steps": [number for number, step in enumerate(old_steps, 1) if step.get("status") == "skipped"],
        "parity_reason": "Compared archived historical and candidate acceptance for the identical SHA256 input; dependency versions are recorded separately.",
    }


def save_json(path: Path, data: dict) -> None:
    staging = path.with_suffix(path.suffix + ".tmp")
    staging.write_text(json.dumps(data, indent=2) + "\n")
    staging.replace(path)


def runtime_preflight(container: str, repo: Path, root: Path, specifications: Path) -> dict:
    inspected = json.loads(subprocess.check_output(["docker", "inspect", container], text=True))[0]
    environment = dict(value.split("=", 1) for value in inspected["Config"]["Env"] if "=" in value)
    expected_environment = {
        "QC_TOOL_VERIFICATION_RUNTIME": "yes",
        "SKIP_INSPIRE_CHECK": "no",
        "USE_LIGHTWEIGHT_VALIDATOR": "no",
        "INCOMING_DIR": "/verification/incoming",
        "WORK_DIR": "/verification/work",
        "BOUNDARY_DIR": "/verification/boundaries",
        "PRODUCT_DIRS": "/verification/specifications",
    }
    for key, expected in expected_environment.items():
        if environment.get(key) != expected:
            raise ValueError(f"Isolated verification runtime requires {key}={expected}")
    mounts = {mount["Destination"]: mount for mount in inspected["Mounts"]}
    external_specifications = root / "production-specifications" if specifications == repo / "product_definitions" else specifications
    expected_mounts = {
        "/usr/local/src/copernicus_quality_tools": (repo, False),
        "/verification/incoming": (root / "incoming", False),
        "/verification/boundaries": (root / "boundaries", False),
        "/verification/work": (root / "work", True),
        "/verification/specifications": (external_specifications, False),
    }
    for destination, (source, writable) in expected_mounts.items():
        mount = mounts.get(destination)
        if not mount or Path(mount["Source"]).resolve() != source.resolve() or mount["RW"] != writable:
            raise ValueError(f"Unexpected verification mount: {destination}")
    if inspected["HostConfig"].get("PortBindings"):
        raise ValueError("Verification runtime must not publish service ports")
    actual_config = json.loads(subprocess.check_output([
        "docker", "exec", container, "python3", "-c",
        "import json,hashlib; from pathlib import Path; paths=['/docker-entrypoint.sh','/etc/squid/squid.conf','/etc/apache2/sites-available/proxy_1.conf','/etc/supervisord.conf']; print(json.dumps({'files':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths},'version_marker':Path('/etc/qc_tool_version.txt').read_text(),'inspire_version':Path('/etc/inspire-validator-version.txt').read_text()}))",
    ], text=True))
    origins = json.loads(subprocess.check_output([
        "docker", "exec", container, "python3", "-c",
        "import importlib,json,hashlib;from pathlib import Path; names=" + repr(PROVENANCE_MODULES) + "; modules={n:importlib.import_module(n) for n in names}; print(json.dumps({n:{'path':str(Path(m.__file__).resolve()),'sha256':hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()} for n,m in modules.items()}))",
    ], text=True))
    verify_module_origins(origins, repo)
    actual_config["module_origins"] = origins
    return {"container": container, "image_id": inspected["Image"], "state": inspected["State"]["Status"], "mounts": list(mounts.values()), "checked_environment": expected_environment, "actual_container_configuration": actual_config}


def available_cases(matrix: dict, incoming: Path) -> list[dict]:
    cases = []
    for product in matrix.get("canonical_products", matrix.get("products", [])):
        if not product.get("canonical_product_ident"):
            continue
        if "selected_negative_control" in product:
            candidates = [product["selected_negative_control"]] if product["selected_negative_control"] else []
            candidates.extend(product.get("negative_fallbacks", []))
        else:
            candidates = product.get("candidates", [])
        for candidate in candidates:
            if candidate.get("source_kind") != "uploaded_zip":
                continue
            path_component(product["canonical_product_ident"], "product identifier")
            path = confined_input(incoming, candidate["filename"])
            if path.is_file():
                cases.append({
                    "product_ident": product["canonical_product_ident"],
                    "definition": product.get("definition", product.get("original_repository_definition")),
                    "candidate": candidate,
                    "filename": candidate["filename"],
                    "selected_tier": product.get("selected_tier"),
                })
                break
    return cases


def run_case(case: dict, args: argparse.Namespace, source: dict) -> dict:
    root = args.evidence_root
    incoming = root / "incoming" / args.username
    path_component(case["product_ident"], "product identifier")
    path = confined_input(incoming, case["filename"])
    recipe_paths = [path for path in args.specification_dir.glob("*.json") if path.stem.lower() == case["product_ident"].lower()]
    if len(recipe_paths) != 1:
        raise ValueError(f"Expected one original specification for {case['product_ident']}")
    recipe_path = recipe_paths[0]
    recipe_hash = sha256_file(recipe_path)
    recipe = json.loads(recipe_path.read_text())
    space = inspect_archive_space(path, root / "work", args.scratch_factor, int(args.reserve_gib * GIB))
    internal_free = int(subprocess.check_output([
        "docker", "exec", args.container, "python3", "-c",
        "import shutil; print(shutil.disk_usage('/var/lib/postgresql/17/main').free)",
    ], text=True).strip())
    space["worker_postgis_filesystem_free_bytes"] = internal_free
    space["worker_postgis_filesystem_space_available"] = internal_free >= space["scratch_required_bytes"]
    record = {
        "product_ident": case["product_ident"],
        "filename": path.name,
        "candidate": case.get("candidate"),
        "selected_tier": case.get("selected_tier"),
        "definition_path": str(recipe_path),
        "definition_sha256": recipe_hash,
        "effective_job_product_dirs": args.effective_product_dirs,
        "specification_source": "repository_default" if args.specification_dir == args.repo / "product_definitions" else "original_production_snapshot",
        "matrix_repository_definition_sha256": case["definition"]["sha256"],
        "specification_matches_matrix_repository_bytes": recipe_hash == case["definition"]["sha256"],
        "input_bytes": path.stat().st_size,
        "source_fingerprint": source["fingerprint"],
        "source_revision": source["revision"],
        "container": args.container,
        "space": space,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "check_selection": "all_current_configured_steps" if args.current_checks else "archived_skips_reproduced",
        "archived_comparison_is_supplementary": args.current_checks,
        "runner_sha256": getattr(args, "runner_sha256", None),
    }
    if not space["space_available"] or not space["worker_postgis_filesystem_space_available"]:
        record.update({"verification_outcome": "insufficient_scratch_space", "passes_all_checks": False, "current_check_outcome": "inconclusive", "parity_outcome": "inconclusive", "parity_matches": None})
        return record
    record["input_sha256"] = sha256_file(path)
    candidate = case.get("candidate", {})
    old_uuid = candidate.get("legacy_job_uuid") or candidate.get("latest_job", {}).get("job_uuid")
    baseline_path = args.legacy_report or (root / "legacy-reports" / (str(uuid.UUID(old_uuid)) + ".json")) if (args.legacy_report or old_uuid) else root / "legacy-reports" / "unavailable.json"
    baseline = json.loads(baseline_path.read_text()) if baseline_path.is_file() else None
    record["baseline_report_path"] = str(baseline_path)
    record["baseline_report_sha256"] = sha256_file(baseline_path) if baseline else None
    if baseline and args.expected_status and baseline.get("status") != args.expected_status:
        raise ValueError("Archived report status differs from the explicitly expected status")
    record["historical_input_identity_confirmed"] = bool(baseline and baseline.get("hash") == record["input_sha256"])
    if not args.current_checks and not record["historical_input_identity_confirmed"]:
        record.update({"verification_outcome": "baseline_identity_unconfirmed", "passes_all_checks": False, "current_check_outcome": "inconclusive", **assess_parity(baseline, None, record["input_sha256"])})
        return record
    job_uuid = str(uuid.uuid4())
    record["job_uuid"] = job_uuid
    report_dir = root / "reports" / case["product_ident"] / job_uuid
    report_dir.mkdir(parents=True)
    cli = [
        "docker", "exec", "-e", "PRODUCT_DIRS=" + args.effective_product_dirs, args.container,
        "timeout", "--signal=TERM", "--kill-after=60s", f"{args.timeout_seconds}s",
        "python3", "-m", "qc_tool.worker.cmd",
        "--job-uuid", job_uuid, "--product", case["product_ident"],
        args.username, path.name,
    ]
    legacy_skips = selected_legacy_skips(baseline, args.current_checks)
    if legacy_skips:
        cli[cli.index(args.username):cli.index(args.username)] = ["--skip-steps", ",".join(map(str, legacy_skips))]
    record["command"] = cli
    started = time.monotonic()
    with (report_dir / "worker-console.log").open("wb") as output:
        process = subprocess.run(cli, stdout=output, stderr=subprocess.STDOUT, check=False)
    record["elapsed_seconds"] = round(time.monotonic() - started, 3)
    record["worker_exit_code"] = process.returncode
    job_dir = root / "work" / ("job_" + uuid.UUID(job_uuid).hex)
    result_path = job_dir / "result.json"
    result = None
    if result_path.is_file():
        result = json.loads(result_path.read_text())
        record.update(assess_result(result, recipe, record["input_sha256"]))
        record["verification_outcome"] = "passed" if record["passes_all_checks"] else "qc_unsuccessful"
    else:
        record.update({"verification_outcome": "worker_result_missing", "passes_all_checks": False})
    artifacts = []
    if job_dir.is_dir():
        for artifact in sorted(job_dir.rglob("*")):
            if artifact.is_file() and "tmp.d" not in artifact.relative_to(job_dir).parts:
                artifacts.append({"path": str(artifact.relative_to(root)), "bytes": artifact.stat().st_size, "sha256": sha256_file(artifact)})
    record["artifacts"] = artifacts
    record["pdf_report_present"] = any(artifact["path"].endswith("_report.pdf") for artifact in artifacts)
    job_specification = job_dir / (case["product_ident"].lower() + ".json")
    record["worker_specification_matches_original_bytes"] = job_specification.is_file() and sha256_file(job_specification) == recipe_hash
    if not record["pdf_report_present"] or process.returncode != 0 or not record["worker_specification_matches_original_bytes"]:
        record["passes_all_checks"] = False
        record["verification_outcome"] = "worker_execution_or_report_failed"
    messages = [str(message) for step in ((result or {}).get("steps") or []) for message in (step.get("messages") or [])]
    attachment_errors = []
    if job_dir.is_dir():
        for attachment in (job_dir / "output.d").glob("*inspire_report.html"):
            attachment_errors.extend(inspire_infrastructure_errors(attachment.read_text(errors="replace")))
    record["inspire_infrastructure_errors"] = attachment_errors
    infrastructure_gap = (
        process.returncode != 0 or not record["pdf_report_present"] or not record["worker_specification_matches_original_bytes"]
        or bool(attachment_errors)
        or any(external_runtime_gap(message) for message in messages)
        or not record.get("input_hash_matches_worker", False)
    )
    if infrastructure_gap:
        record["passes_all_checks"] = False
        record["verification_outcome"] = "runtime_infrastructure_gap"
    record["current_check_outcome"] = current_check_outcome(result, record["passes_all_checks"], infrastructure_gap)
    record.update(assess_parity(baseline, result, record["input_sha256"], infrastructure_error=infrastructure_gap, candidate_is_complete=record["passes_all_checks"]))
    record["finished_utc"] = datetime.now(timezone.utc).isoformat()
    save_json(report_dir / "verification.json", record)
    return record


def main() -> int:
    loaded_runner_sha256 = sha256_file(Path(__file__))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--matrix", type=Path)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--specification-dir", type=Path, help="Read-only original specification directory mounted in the worker.")
    parser.add_argument("--container", required=True)
    parser.add_argument("--current-checks", action="store_true", help="Execute every current configured step without archived skips; require protected check bytes to match HEAD. Archived comparison is supplementary and missing historical identity does not block current QC.")
    parser.add_argument("--username", default="legacy-probe")
    parser.add_argument("--product", help="Limit available matrix cases to this canonical identifier.")
    parser.add_argument("--exclude-product", action="append", default=[], help="Defer a canonical product from this run, keeping its coverage pending.")
    parser.add_argument("--include-product", action="append", default=[], help="Restrict a retry cohort to these canonical products; repeat as needed.")
    parser.add_argument("--max-legacy-runtime-seconds", type=float, help="Run only cases with a known historical runtime below this bound; defer the rest.")
    parser.add_argument("--priority-delivery-id", type=int, action="append", default=[], help="Prioritize this known historical delivery within the chosen batch.")
    parser.add_argument("--filename", help="Run this explicitly chosen ZIP with --product, even if not a matrix candidate.")
    parser.add_argument("--legacy-report", type=Path, help="Exact archived production job report for an explicitly chosen ZIP.")
    parser.add_argument("--expected-status", choices=("ok", "failed", "partial", "error"), help="Check, never override, the archived report status.")
    parser.add_argument("--scratch-factor", type=float, default=2.5)
    parser.add_argument("--reserve-gib", type=float, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=90000)
    args = parser.parse_args()
    args.runner_sha256 = loaded_runner_sha256
    args.evidence_root = args.evidence_root.resolve(strict=True)
    args.repo = args.repo.resolve(strict=True)
    args.specification_dir = (args.specification_dir or args.repo / "product_definitions").resolve(strict=True)
    args.effective_product_dirs = "/usr/local/src/copernicus_quality_tools/product_definitions" if args.specification_dir == args.repo / "product_definitions" else "/verification/specifications"
    if args.scratch_factor < 1 or args.reserve_gib < 0 or args.timeout_seconds < 1:
        parser.error("Scratch factor must be >=1, reserve >=0, and timeout positive.")
    if any("/" in name or "\\" in name or name in ("", ".", "..") for name in (args.username, args.filename or "unused")):
        parser.error("Username and filename must be individual path components.")
    matrix_path = args.matrix or args.evidence_root / "candidate-matrix.json"
    matrix = json.loads(matrix_path.read_text())
    lock_file = (args.evidence_root / "runtime" / "worker-qc.lock").open("a+")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error("Another verification batch already owns this isolated worker.")
    running = json.loads(subprocess.check_output([
        "docker", "exec", args.container, "python3", "-c",
        "from pathlib import Path;import json; running=[]\nfor p in Path('/proc').glob('[0-9]*/cmdline'):\n try:\n  if b'qc_tool.worker.cmd' in p.read_bytes().split(b'\\0'):running.append(p.parent.name)\n except (OSError,PermissionError):pass\nprint(json.dumps(running))",
    ], text=True))
    if running:
        parser.error("A QC job is already running in this isolated worker; wait for its result.")
    if (args.evidence_root / "work" / "product_definitions").exists():
        parser.error("Verification work storage must not contain uploaded specification overrides.")
    runtime = runtime_preflight(args.container, args.repo, args.evidence_root, args.specification_dir)
    incoming = args.evidence_root / "incoming" / args.username
    if args.filename:
        if not args.product:
            parser.error("--filename requires --product.")
        product = next((p for p in matrix.get("canonical_products", matrix.get("products", [])) if p["canonical_product_ident"] == args.product), None)
        if product and "definition" not in product:
            product = {**product, "definition": product.get("original_repository_definition")}
        if not product or not product.get("definition"):
            parser.error("Explicit product must have an original recipe in the matrix.")
        cases = [{"product_ident": args.product, "filename": args.filename, "definition": product["definition"], "selected_tier": "explicit_readonly_production_sample"}]
    else:
        cases = available_cases(matrix, incoming)
        if args.product:
            cases = [case for case in cases if case["product_ident"] == args.product]
    cases = [case for case in cases if case["product_ident"] not in args.exclude_product]
    if args.include_product:
        cases = [case for case in cases if case["product_ident"] in args.include_product]
    if args.max_legacy_runtime_seconds is not None:
        cases = [case for case in cases if case.get("candidate", {}).get("legacy_runtime_seconds") is not None and case["candidate"]["legacy_runtime_seconds"] < args.max_legacy_runtime_seconds]
    if not cases:
        print("No chosen production ZIP is present in the isolated incoming directory.", file=sys.stderr)
        return 2
    priority = {delivery_id: rank for rank, delivery_id in enumerate(args.priority_delivery_id)}
    cases.sort(key=lambda case: (priority.get(case.get("candidate", {}).get("delivery_id"), len(priority)), case.get("candidate", {}).get("legacy_runtime_seconds", float("inf")), (incoming / case["filename"]).stat().st_size))
    source = source_snapshot(args.repo)
    protected = protected_checks_snapshot(args.repo) if args.current_checks else None
    run_uuid = str(uuid.uuid4())
    source_path = args.evidence_root / "runtime" / f"source-{run_uuid}.json"
    save_json(source_path, source)
    summary_path = args.evidence_root / "reports" / f"run-{run_uuid}.json"
    summary = {"run_uuid": run_uuid, "scope": "Every current configured check without historical skips; archived comparison supplementary; no frontend uploads/submissions" if args.current_checks else "Archived-baseline parity for identical production ZIPs, reproducing any recorded legacy skips; no frontend uploads/submissions", "current_checks": args.current_checks, "runner_path": str(Path(__file__).resolve()), "runner_sha256": loaded_runner_sha256, "source_snapshot": str(source_path), "protected_checks": protected, "runtime": runtime, "cases": []}
    for case in cases:
        if args.current_checks:
            try:
                before = protected_checks_snapshot(args.repo)
                if before["fingerprint"] != protected["fingerprint"] or source_snapshot(args.repo)["fingerprint"] != source["fingerprint"]:
                    raise ValueError("Source changed before the next QC case")
                case_runtime = runtime_preflight(args.container, args.repo, args.evidence_root, args.specification_dir)
            except ValueError as error:
                summary["stopped_reason"] = str(error)
                break
        print(f"Checking {case['product_ident']}: {case['filename']}", flush=True)
        record = run_case(case, args, source)
        if args.current_checks:
            record["protected_checks_before"] = before["fingerprint"]
            record["imported_module_origins"] = case_runtime["actual_container_configuration"]["module_origins"]
            try:
                after = protected_checks_snapshot(args.repo)
                record["protected_checks_after"] = after["fingerprint"]
                record["source_unchanged_during_case"] = after["fingerprint"] == before["fingerprint"] and source_snapshot(args.repo)["fingerprint"] == source["fingerprint"]
                if not record["source_unchanged_during_case"]:
                    raise ValueError("Source changed while QC was running")
            except ValueError as error:
                summary["stopped_reason"] = str(error)
                record.update({"passes_all_checks": False, "current_check_outcome": "inconclusive", "parity_outcome": "inconclusive", "parity_matches": None, "source_unchanged_during_case": False})
            if record.get("job_uuid"):
                save_json(args.evidence_root / "reports" / case["product_ident"] / record["job_uuid"] / "verification.json", record)
        summary["cases"].append(record)
        save_json(summary_path, summary)
        print(f"  {record['verification_outcome']}; current: {record['current_check_outcome']}; parity: {record['parity_outcome']}; all checks pass: {record['passes_all_checks']}", flush=True)
        if summary.get("stopped_reason"):
            break
    summary["source_unchanged_during_run"] = source_snapshot(args.repo)["fingerprint"] == source["fingerprint"]
    summary["chosen_case_count"] = len(cases)
    save_json(summary_path, summary)
    print(f"Evidence: {summary_path}", flush=True)
    lock_file.close()
    return 0 if batch_succeeded(summary) else 1


if __name__ == "__main__":
    raise SystemExit(main())
