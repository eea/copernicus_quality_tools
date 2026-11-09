"""A synthetic execution exercises physical artifacts without QC databases."""

from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from qc_tool.common import CONFIG, load_job_result
from qc_tool.jobs import create_job_paths, read_job_context
from qc_tool.worker import dispatch


JOB_UUID = "01234567-89ab-cdef-0123-456789abcdef"


class WorkerJobLayoutTests(TestCase):
    def test_success_preserves_evidence_and_cleans_only_private_scratch(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            jobs, scratch, recipes = (root / name for name in ("jobs", "scratch", "recipes"))
            scratch.mkdir(mode=0o700)
            recipes.mkdir()
            specification = recipes / "EXAMPLE.json"
            original = json.dumps({"description": "Example", "steps": [{
                "check_ident": "synthetic.test", "required": True,
            }]}).encode("utf-8")
            specification.write_bytes(original)
            source = root / "delivery.zip"
            source.write_bytes(b"exact-original-input-bytes")
            paths = create_job_paths(jobs, JOB_UUID)

            def run_check(params, status):
                self.assertNotEqual(params["tmp_dir"].parent, paths.directory)
                (params["tmp_dir"] / "materialized-data").write_bytes(b"temporary")
                (params["output_dir"] / "attachment.gpkg").write_bytes(b"check-output")
                status.add_attachment("attachment.gpkg")
                status.set_status_property("product_unit_code", "007")
                status.set_status_property("reference_year", "2024")
                status.set_status_property("hash", "b" * 64)
                status.set_status_property("hash_files", ["selected.shp"])

            def report(path, identity):
                self.assertEqual(identity, JOB_UUID)
                path.write_bytes(b"synthetic-pdf")

            with (patch.dict(CONFIG, {
                    "work_dir": jobs, "product_dirs": [recipes], "scratch_dir": scratch,
                    "specifications_dir": root / "uploads", "leave_jobdir": False,
                  }),
                  patch.object(dispatch, "create_connection_manager", return_value=nullcontext(object())),
                  patch.object(dispatch, "resolve_boundary_generation", return_value=SimpleNamespace(
                      path=root, generation_id="boundary-generation", managed=True,
                  )),
                  patch.object(dispatch, "import_module", return_value=SimpleNamespace(run_check=run_check)),
                  patch.object(dispatch, "generate_pdf_report", side_effect=report),
                  patch.object(dispatch, "signal"), patch.object(dispatch, "alarm"),
                  patch.object(dispatch, "get_qc_tool_version", return_value="3.0.0")):
                result = dispatch.dispatch(JOB_UUID, "tester", source, "example")
                self.assertEqual(load_job_result(JOB_UUID), result)

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["hash"], "b" * 64)  # Existing QC meaning is retained.
            context = read_job_context(paths)
            self.assertEqual(context["input"]["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(context["input"]["reported_hash"], result["hash"])
            self.assertEqual(context["input"]["hash_files"], ["selected.shp"])
            self.assertEqual(context["specification"]["filename"], "EXAMPLE.json")
            self.assertEqual(context["boundary"]["generation_id"], "boundary-generation")
            self.assertEqual(context["execution"]["status"], "ok")
            self.assertEqual(context["product_unit_code"], "007")
            self.assertEqual(context["reference_period"], "2024")
            self.assertEqual((paths.specification_dir / "EXAMPLE.json").read_bytes(), original)
            self.assertEqual((paths.reports_dir / "delivery_report.pdf").read_bytes(), b"synthetic-pdf")
            self.assertEqual((paths.output_dir / "attachment.gpkg").read_bytes(), b"check-output")
            self.assertEqual(list(scratch.iterdir()), [])
            self.assertEqual(source.read_bytes(), b"exact-original-input-bytes")
