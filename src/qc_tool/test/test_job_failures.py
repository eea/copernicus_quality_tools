"""Expected setup failures stay actionable without revealing private diagnostics."""

from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from qc_tool.boundaries.errors import BoundaryGenerationUnavailable, BoundaryPackageConfigurationError
from qc_tool.jobs.failures import BOUNDARY_UNAVAILABLE_MESSAGE, UNEXPECTED_JOB_ERROR, public_job_failure


class PublicJobFailureTests(TestCase):
    def test_missing_boundaries_expose_only_the_typed_public_message(self):
        error = BoundaryGenerationUnavailable("/private/storage/diagnostic")
        result = public_job_failure(error)
        self.assertEqual(result, {"error_code": "boundary_generation_unavailable",
                                  "error_message": BOUNDARY_UNAVAILABLE_MESSAGE})
        self.assertNotIn("/private", str(result))

    def test_configuration_failures_retain_their_safe_type(self):
        error = BoundaryPackageConfigurationError("unsafe pointer at /private/path")
        self.assertEqual(public_job_failure(error), {
            "error_code": error.code, "error_message": error.user_message})

    def test_unexpected_failures_do_not_expose_exception_text(self):
        self.assertEqual(public_job_failure(OSError("private credential value")),
                         {"error_message": UNEXPECTED_JOB_ERROR})


class DispatchSetupFailureTests(TestCase):
    def test_missing_boundaries_are_retained_as_an_expected_setup_failure(self):
        from qc_tool.worker import dispatch

        manager = SimpleNamespace(job_dir=Path("/unused/job"))
        saved = []
        error = BoundaryGenerationUnavailable("legacy boundary directories are incomplete")
        with (patch.object(dispatch, "load_product_definition", return_value={"steps": []}),
              patch.object(dispatch, "create_jobdir_manager", return_value=nullcontext(manager)),
              patch.object(dispatch, "copy_product_definition_to_job"),
              patch.object(dispatch, "make_signature", return_value="a" * 64),
              patch.object(dispatch, "store_job_result", side_effect=lambda value: saved.append(deepcopy(value))),
              patch.object(dispatch, "resolve_boundary_generation", side_effect=error),
              patch.object(dispatch, "create_connection_manager") as database,
              patch.object(dispatch, "generate_pdf_report"),
              self.assertLogs(dispatch.log, level="ERROR"),
              self.assertRaises(BoundaryGenerationUnavailable)):
            dispatch.dispatch("01234567-89ab-cdef-0123-456789abcdef", "test-user", Path("sample.zip"), "test")
        database.assert_not_called()
        self.assertEqual(saved[-1]["status"], "error")
        self.assertEqual(saved[-1]["steps"], [])
        self.assertEqual(saved[-1]["error_code"], "boundary_generation_unavailable")
        self.assertEqual(saved[-1]["error_message"], BOUNDARY_UNAVAILABLE_MESSAGE)
