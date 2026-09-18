"""New opaque unit observations coexist with retained geographic contracts."""

from contextlib import ExitStack, nullcontext
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from qc_tool.worker.status import CheckStatus
from qc_tool.worker.product_units import merge_step_product_unit_metadata


class WorkerProductUnitTests(TestCase):
    def test_status_preserves_numeric_padding_and_geographic_suffix(self):
        for value in ("007", "EE001L1"):
            status = CheckStatus()
            status.set_status_property("product_unit_code", value)
            merge_step_product_unit_metadata({}, status)
            self.assertEqual(status.status_properties["product_unit_code"], value.casefold())
            self.assertNotIn("aoi_code", status.status_properties)

    def test_conflicting_steps_cannot_choose_the_last_unit(self):
        status = CheckStatus()
        status.set_status_property("product_unit_code", "008")
        merge_step_product_unit_metadata({"product_unit_code": "007"}, status)
        self.assertIsNone(status.status_properties["product_unit_code"])
        self.assertTrue(status.params["_product_unit_code_conflict"])

    def test_dispatch_emits_verified_opaque_unit_without_legacy_null_alias(self):
        result = self.dispatch_observations(["007"])
        self.assertEqual(result["product_unit_code"], "007")
        self.assertNotIn("aoi_code", result)

    def test_status_conflict_remains_after_null_or_malformed_then_valid(self):
        for invalid in (None, "", 7, {"code": "007"}):
            with self.subTest(invalid=invalid):
                status = CheckStatus()
                for value in ("unit-a", invalid, "unit-b"):
                    status.set_status_property("product_unit_code", value)
                self.assertIsNone(status.status_properties["product_unit_code"])
                self.assertTrue(status.params["_product_unit_code_conflict"])

    def test_dispatch_conflict_remains_after_null_or_malformed_then_valid(self):
        for invalid in (None, "", 7, {"code": "007"}):
            with self.subTest(invalid=invalid):
                result = self.dispatch_observations(["unit-a", invalid, "unit-b"])
                self.assertIsNone(result["product_unit_code"])
                self.assertNotIn("aoi_code", result)
                self.assertTrue(any("conflicting identifiers" in message for message in result["steps"][-1]["messages"]))

    def dispatch_observations(self, values):
        from qc_tool.worker.dispatch import dispatch
        prefix = "qc_tool.worker.dispatch."
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            source = root / "unit.zip"
            source.write_bytes(b"input")
            manager = SimpleNamespace(job_dir=root, tmp_dir=root, output_dir=root)
            definition = {"product_units": ["007"], "steps": [{"check_ident": "custom.naming", "required": True} for _ in values]}
            observations = iter(values)
            def run_check(params, status):
                status.set_status_property("product_unit_code", next(observations))
            replacements = {
                "load_product_definition": definition,
                "create_jobdir_manager": nullcontext(manager),
                "create_connection_manager": nullcontext(object()),
                "resolve_boundary_generation": SimpleNamespace(path=root, generation_id="test"),
                "import_module": SimpleNamespace(run_check=run_check),
                "get_timeout": {"seconds": 60},
                "get_qc_tool_version": "test",
            }
            for name, value in replacements.items():
                stack.enter_context(patch(prefix + name, return_value=value))
            for name in ("copy_product_definition_to_job", "store_job_result", "generate_pdf_report", "signal", "alarm"):
                stack.enter_context(patch(prefix + name))
            return dispatch(str(uuid4()), "owner", source, "sample")
