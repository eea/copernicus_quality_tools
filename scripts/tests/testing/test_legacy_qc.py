"""Evidence-boundary tests for the real production-QC runner."""

from pathlib import Path
import argparse
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch, Mock
import uuid
import zipfile

from scripts.testing.legacy_qc import assess_parity, assess_result, available_cases, inspect_archive_space, runtime_preflight, inspire_infrastructure_errors, external_runtime_gap, confined_input, verify_module_origins, PROVENANCE_MODULES, sha256_file, protected_checks_snapshot, selected_legacy_skips, current_check_outcome, run_case, batch_succeeded


class VerificationEvidenceTests(unittest.TestCase):
    def test_null_blueprint_entries_are_not_completed_or_executed_checks(self):
        recipe = {"steps": [{"check_ident": "unzip"}, {"check_ident": "metadata"}]}
        stopped = {"status": "failed", "hash": "hash", "steps": [{"check_ident": "unzip", "status": "aborted"}, {"check_ident": "metadata", "status": None}]}
        assessment = assess_result(stopped, recipe, "hash")
        self.assertEqual(assessment["configured_step_entry_count"], 2)
        self.assertEqual(assessment["executed_step_count"], 1)
        self.assertFalse(assessment["all_configured_steps_completed"])
        stopped["steps"][1]["status"] = "skipped"
        self.assertEqual(assess_result(stopped, recipe, "hash")["executed_step_count"], 1)
        self.assertFalse(assess_result(stopped, recipe, "hash")["all_configured_steps_completed"])
        stopped["steps"][1]["status"] = "failed"
        self.assertTrue(assess_result(stopped, recipe, "hash")["all_configured_steps_completed"])
        self.assertFalse(assess_result(stopped, recipe, "hash")["passes_all_checks"])

    def test_current_batch_cannot_exit_success_with_inconclusive_runtime_evidence(self):
        case = {"passes_all_checks": True, "current_check_outcome": "passed"}
        summary = {"cases": [case], "chosen_case_count": 1, "current_checks": True, "source_unchanged_during_run": True}
        self.assertTrue(batch_succeeded(summary))
        case["current_check_outcome"] = "inconclusive"
        self.assertFalse(batch_succeeded(summary))
        case["passes_all_checks"] = False
        self.assertFalse(batch_succeeded(summary))

    def test_protected_check_guard_rejects_modified_missing_and_extra_files(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            for relative in ("src/qc_tool/raster/gap.py", "src/qc_tool/vector/overlap.py"):
                path = repo / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# original check\n")
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "add", "src"], cwd=repo, check=True)
            subprocess.run(["git", "-c", "user.name=Verification", "-c", "user.email=verification@example.invalid", "commit", "-qm", "checks"], cwd=repo, check=True)
            initial = protected_checks_snapshot(repo)
            self.assertTrue(initial["all_tracked_bytes_match_head"])
            path = repo / "src/qc_tool/raster/gap.py"
            path.write_text("# modified check\n")
            with self.assertRaisesRegex(ValueError, "gap.py"):
                protected_checks_snapshot(repo)
            path.write_text("# original check\n")
            extra = path.parent / "extra.py"
            extra.write_text("# extra check\n")
            with self.assertRaisesRegex(ValueError, "extra.py"):
                protected_checks_snapshot(repo)
            extra.unlink()
            self.assertEqual(protected_checks_snapshot(repo)["fingerprint"], initial["fingerprint"])
            path.unlink()
            with self.assertRaisesRegex(ValueError, "gap.py"):
                protected_checks_snapshot(repo)

    def test_current_checks_never_reproduce_historical_skips(self):
        baseline = {"steps": [{"status": "ok"}, {"status": "skipped"}, {"status": "failed"}]}
        self.assertEqual(selected_legacy_skips(baseline, False), [2])
        self.assertEqual(selected_legacy_skips(baseline, True), [])
        self.assertEqual(selected_legacy_skips(None, True), [])
        self.assertEqual(current_check_outcome({"status": "failed"}, False, False), "failed")
        self.assertEqual(current_check_outcome({"status": "failed"}, False, True), "inconclusive")
        self.assertEqual(current_check_outcome({"status": "ok"}, False, False), "inconclusive")

    def test_current_smoke_runs_without_archived_identity_but_cannot_claim_parity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            incoming = root / "incoming" / "probe"
            incoming.mkdir(parents=True)
            archive = incoming / "delivery.zip"
            with zipfile.ZipFile(archive, "w") as writer:
                writer.writestr("input.txt", "data")
            specs = root / "specifications"
            specs.mkdir()
            recipe = {"steps": [{"check_ident": "unzip"}, {"check_ident": "metadata"}]}
            spec = specs / "product.json"
            spec.write_text(json.dumps(recipe))
            (root / "work").mkdir()
            args = argparse.Namespace(evidence_root=root, username="probe", specification_dir=specs, scratch_factor=1, reserve_gib=0, container="isolated", effective_product_dirs="/verification/specifications", repo=root, legacy_report=None, expected_status=None, timeout_seconds=10, current_checks=True)
            case = {"product_ident": "product", "filename": archive.name, "definition": {"sha256": sha256_file(spec)}}
            system_error = False
            worker_status = "ok"
            wrong_worker_hash = False
            def worker(command, **kwargs):
                self.assertNotIn("--skip-steps", command)
                job_uuid = command[command.index("--job-uuid") + 1]
                job = root / "work" / ("job_" + uuid.UUID(job_uuid).hex)
                job.mkdir()
                (job / "product.json").write_bytes(spec.read_bytes())
                (job / "product_report.pdf").write_bytes(b"%PDF report")
                (job / "result.json").write_text(json.dumps({"status": worker_status, "hash": sha256_file(archive) if wrong_worker_hash is False else wrong_worker_hash, "steps": [{"check_ident": step["check_ident"], "status": "ok"} for step in recipe["steps"]]}))
                if system_error:
                    (job / "output.d").mkdir()
                    (job / "output.d/input_inspire_report.html").write_text('<div class="FailureMessage"><textarea>System error in the Executable Test Suite. Remote resource unavailable.</textarea></div>')
                return Mock(returncode=0)
            with patch("scripts.testing.legacy_qc.subprocess.check_output", return_value=str(10**12)), patch("scripts.testing.legacy_qc.subprocess.run", side_effect=worker) as launched:
                record = run_case(case, args, {"fingerprint": "source", "revision": "revision"})
            self.assertEqual(launched.call_count, 1)
            self.assertFalse(record["historical_input_identity_confirmed"])
            self.assertTrue(record["passes_all_checks"])
            self.assertEqual(record["current_check_outcome"], "passed")
            self.assertEqual(record["parity_outcome"], "inconclusive")
            system_error = True
            with patch("scripts.testing.legacy_qc.subprocess.check_output", return_value=str(10**12)), patch("scripts.testing.legacy_qc.subprocess.run", side_effect=worker):
                infrastructure = run_case(case, args, {"fingerprint": "source", "revision": "revision"})
            self.assertFalse(infrastructure["passes_all_checks"])
            self.assertEqual(infrastructure["current_check_outcome"], "inconclusive")
            self.assertFalse(batch_succeeded({"cases": [infrastructure], "chosen_case_count": 1, "current_checks": True, "source_unchanged_during_run": True}))
            system_error = False
            worker_status = "failed"
            for invalid_hash in ("incorrect", None):
                wrong_worker_hash = invalid_hash
                with patch("scripts.testing.legacy_qc.subprocess.check_output", return_value=str(10**12)), patch("scripts.testing.legacy_qc.subprocess.run", side_effect=worker):
                    wrong_hash = run_case(case, args, {"fingerprint": "source", "revision": "revision"})
                self.assertFalse(wrong_hash["input_hash_matches_worker"])
                self.assertEqual(wrong_hash["current_check_outcome"], "inconclusive")

    def test_matrix_input_cannot_escape_by_path_or_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            incoming = root / "incoming"
            incoming.mkdir()
            secret = root / "private.zip"
            secret.write_bytes(b"private")
            for name in ("../private.zip", "..\\private.zip", "/private.zip"):
                with self.assertRaises(ValueError):
                    confined_input(incoming, name)
            (incoming / "linked.zip").symlink_to(secret)
            with self.assertRaises(ValueError):
                confined_input(incoming, "linked.zip")
            self.assertEqual(confined_input(incoming, "safe.zip"), incoming / "safe.zip")

    def test_module_provenance_rejects_an_image_module_with_matching_source_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            origins = {}
            for name in PROVENANCE_MODULES:
                relative = Path("src").joinpath(*name.split(".")).with_suffix(".py")
                path = repo / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# source\n")
                origins[name] = {"path": str(Path("/usr/local/src/copernicus_quality_tools") / relative), "sha256": sha256_file(path)}
            verify_module_origins(origins, repo)
            origins["qc_tool.common"]["path"] = "/image/qc_tool/common.py"
            with self.assertRaisesRegex(ValueError, "unexpected source"):
                verify_module_origins(origins, repo)
    def test_inspire_system_error_is_inconclusive_but_metadata_rejection_is_not(self):
        system = '<div class="FailureMessage"><textarea>System error in the Executable Test Suite. Please contact a system administrator. Error information:Code list http://inspire.ec.europa.eu/theme cannot be accessed.</textarea></div>'
        self.assertEqual(len(inspire_infrastructure_errors(system)), 1)
        html_as_xml = '<div class="FailureMessage"><textarea>System error in the Executable Test Suite. Error information:The element type hr must be terminated by the matching end-tag.</textarea></div>'
        self.assertEqual(len(inspire_infrastructure_errors(html_as_xml)), 1)
        invalid_metadata = '<div>Metadata does not declare a valid INSPIRE theme keyword.</div>'
        self.assertEqual(inspire_infrastructure_errors(invalid_metadata), [])
        expression = '<div class="Expression"><textarea>System error in the Executable Test Suite. Generic expression source.</textarea></div>'
        self.assertEqual(inspire_infrastructure_errors(expression), [])
        self.assertTrue(external_runtime_gap("Mask mask_default_010m_eu.tif not available"))
        self.assertFalse(external_runtime_gap("Raster values outside the mask are invalid"))
        self.assertTrue(external_runtime_gap("Unable to validate metadata of input.xml: Connection timeout."))
        self.assertTrue(external_runtime_gap("Metadata of input.xml could not be validated, validation service is busy."))
        self.assertTrue(external_runtime_gap("Report s03_input_inspire_report.html is not available: error"))
        self.assertFalse(external_runtime_gap("Metadata file input.xml is not in INSPIRE XML format and cannot be validated: HTTP 400"))
        self.assertFalse(external_runtime_gap("Metadata of input.xml did not pass INSPIRE validation. See report for details."))
    def test_strict_positive_and_negative_parity_never_counts_missing_result(self):
        passed = {"status": "ok", "hash": "hash", "steps": []}
        failed = {"status": "failed", "hash": "hash", "steps": []}
        self.assertEqual(assess_parity(failed, passed, "hash")["parity_outcome"], "mismatch")
        self.assertEqual(assess_parity(passed, failed, "hash")["parity_outcome"], "mismatch")
        self.assertEqual(assess_parity(failed, None, "hash")["parity_outcome"], "inconclusive")
        self.assertIsNone(assess_parity(failed, failed, "hash", infrastructure_error=True)["parity_matches"])
        self.assertEqual(assess_parity(failed, failed, "hash")["parity_outcome"], "matched_nonpass")
        self.assertEqual(assess_parity(passed, passed, "hash", candidate_is_complete=False)["parity_outcome"], "inconclusive")
        failed_service = {**failed, "steps": [{"check_ident": "inspire", "status": "failed", "messages": ["Unable to validate metadata of x.xml: connection timeout"]}]}
        self.assertEqual(assess_parity(failed_service, failed, "hash")["parity_outcome"], "inconclusive")
        null_messages = {**failed, "steps": [{"check_ident": "unzip", "status": "aborted", "messages": ["Invalid archive"]}, {"check_ident": "metadata", "status": None, "messages": None}]}
        self.assertEqual(assess_parity(null_messages, failed, "hash")["parity_outcome"], "matched_nonpass")
    def test_ok_status_cannot_hide_a_missing_or_skipped_configured_check(self):
        recipe = {"steps": [{"check_ident": "unzip"}, {"check_ident": "metadata"}]}
        partial = {"status": "ok", "hash": "hash", "steps": [{"check_ident": "unzip", "status": "ok"}]}
        self.assertFalse(assess_result(partial, recipe, "hash")["passes_all_checks"])
        skipped = {**partial, "steps": partial["steps"] + [{"check_ident": "metadata", "status": "skipped"}]}
        self.assertFalse(assess_result(skipped, recipe, "hash")["passes_all_checks"])
        complete = {**partial, "steps": partial["steps"] + [{"check_ident": "metadata", "status": "ok"}]}
        self.assertTrue(assess_result(complete, recipe, "hash")["passes_all_checks"])
        self.assertFalse(assess_result(complete, recipe, "different")["passes_all_checks"])

    def test_scratch_guard_uses_uncompressed_bytes_and_reserve(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "delivery.zip"
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as writer:
                writer.writestr("raster.tif", b"0" * 10000)
            with patch("scripts.testing.legacy_qc.shutil.disk_usage") as usage:
                usage.return_value.free = 20000
                result = inspect_archive_space(archive, root, 2.5, 1000)
            self.assertEqual(result["declared_uncompressed_bytes"], 10000)
            self.assertEqual(result["scratch_required_bytes"], 26000)
            self.assertFalse(result["space_available"])
            self.assertEqual(list(root.iterdir()), [archive])

    def test_invalid_archive_metadata_does_not_prevent_the_worker_negative_check(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "invalid.zip"
            archive.write_bytes(b"This is not a ZIP archive.")
            with patch("scripts.testing.legacy_qc.shutil.disk_usage") as usage:
                usage.return_value.free = 20000
                result = inspect_archive_space(archive, root, 2.5, 1000)
            self.assertFalse(result["archive_metadata_readable"])
            self.assertTrue(result["space_available"])
            self.assertEqual(archive.read_bytes(), b"This is not a ZIP archive.")

    def test_matrix_selects_available_uploaded_zip_and_keeps_one_per_product(self):
        with tempfile.TemporaryDirectory() as directory:
            incoming = Path(directory)
            (incoming / "second.zip").write_bytes(b"zip")
            matrix = {"canonical_products": [{"canonical_product_ident": "product", "definition": {}, "candidates": [
                {"filename": "missing.zip", "source_kind": "uploaded_zip"},
                {"filename": "second.zip", "source_kind": "s3"},
                {"filename": "second.zip", "source_kind": "uploaded_zip"},
            ]}]}
            cases = available_cases(matrix, incoming)
            self.assertEqual(len(cases), 1)
            self.assertEqual(cases[0]["filename"], "second.zip")

    def test_preflight_rejects_mutable_input_or_skipped_metadata(self):
        repo = Path("/repo")
        root = Path("/evidence")
        specifications = root / "specifications"
        environment = {
            "QC_TOOL_VERIFICATION_RUNTIME": "yes", "SKIP_INSPIRE_CHECK": "no",
            "USE_LIGHTWEIGHT_VALIDATOR": "no", "INCOMING_DIR": "/verification/incoming",
            "WORK_DIR": "/verification/work", "BOUNDARY_DIR": "/verification/boundaries",
            "PRODUCT_DIRS": "/verification/specifications",
        }
        mounts = [
            {"Destination": target, "Source": str(source), "RW": writable}
            for target, source, writable in [
                ("/usr/local/src/copernicus_quality_tools", repo, False),
                ("/verification/incoming", root / "incoming", False),
                ("/verification/boundaries", root / "boundaries", False),
                ("/verification/work", root / "work", True),
                ("/verification/specifications", specifications, False),
            ]
        ]
        inspection = [{"Config": {"Env": [f"{k}={v}" for k, v in environment.items()]}, "Mounts": mounts, "HostConfig": {"PortBindings": {}}, "Image": "image", "State": {"Status": "running"}}]
        with patch("scripts.testing.legacy_qc.subprocess.check_output", side_effect=[json.dumps(inspection), json.dumps({"files": {}, "inspire_version": "2026.1.1"}), json.dumps({})]), patch("scripts.testing.legacy_qc.verify_module_origins"):
            self.assertEqual(runtime_preflight("isolated", repo, root, specifications)["image_id"], "image")
        mounts[1]["RW"] = True
        with patch("scripts.testing.legacy_qc.subprocess.check_output", return_value=json.dumps(inspection)):
            with self.assertRaisesRegex(ValueError, "mount"):
                runtime_preflight("isolated", repo, root, specifications)
        mounts[1]["RW"] = False
        inspection[0]["Config"]["Env"] = [f"{k}={v if k != 'SKIP_INSPIRE_CHECK' else 'yes'}" for k, v in environment.items()]
        with patch("scripts.testing.legacy_qc.subprocess.check_output", return_value=json.dumps(inspection)):
            with self.assertRaisesRegex(ValueError, "SKIP_INSPIRE_CHECK"):
                runtime_preflight("isolated", repo, root, specifications)


if __name__ == "__main__":
    unittest.main()
