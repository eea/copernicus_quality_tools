"""A required CI check cannot succeed when prerequisite coverage did not run."""

import importlib.util
from pathlib import Path
import unittest


path = Path(__file__).resolve().parents[2] / "ci" / "check_results.py"
spec = importlib.util.spec_from_file_location("check_results", path)
results = importlib.util.module_from_spec(spec)
spec.loader.exec_module(results)


class RequiredCheckTests(unittest.TestCase):
    def test_all_required_jobs_must_succeed(self):
        self.assertEqual(results.unsuccessful_jobs({
            "frontend": {"result": "success"}, "worker": {"result": "success"},
        }), [])

    def test_missing_coverage_does_not_become_a_green_check(self):
        for result in ("failure", "cancelled", "skipped", None):
            with self.subTest(result=result):
                self.assertEqual(results.unsuccessful_jobs({
                    "source": {"result": "success"}, "frontend": {"result": result},
                }), ["frontend"])
        self.assertTrue(results.unsuccessful_jobs({}))
