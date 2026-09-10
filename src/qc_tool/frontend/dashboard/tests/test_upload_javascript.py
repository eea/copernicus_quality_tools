"""Run upload event regressions when the JavaScript runtime is available."""

from pathlib import Path
import shutil
import subprocess
import unittest


class UploadPageJavaScriptTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for JavaScript event tests")
    def test_upload_components_and_adapters(self):
        suites = sorted((Path(__file__).parent / "javascript").glob("*.test.cjs"))
        self.assertTrue(suites, "Upload interaction suites must be discoverable")
        result = subprocess.run(
            [shutil.which("node"), "--test", *(str(suite) for suite in suites)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
