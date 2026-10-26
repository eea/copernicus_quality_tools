"""Keep the preinstalled browsers and their npm driver on the same release."""

import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[3]
BROWSER = ROOT / "scripts" / "ci" / "browser"


class BrowserRuntimeTests(unittest.TestCase):
    def test_digest_pinned_browser_image_matches_locked_packages(self):
        dockerfile = (BROWSER / "Dockerfile").read_text(encoding="utf-8")
        base = re.search(
            r"^FROM mcr\.microsoft\.com/playwright:"
            r"v(?P<version>\d+\.\d+\.\d+)-noble@sha256:[0-9a-f]{64}$",
            dockerfile,
            re.MULTILINE,
        )
        self.assertIsNotNone(base, "Pin the official Playwright image version and digest")
        version = base.group("version")
        package = json.loads((BROWSER / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((BROWSER / "package-lock.json").read_text(encoding="utf-8"))

        self.assertEqual(package["devDependencies"]["@playwright/test"], version)
        self.assertEqual(lock["packages"][""]["devDependencies"]["@playwright/test"], version)
        for dependency in ("@playwright/test", "playwright", "playwright-core"):
            with self.subTest(dependency=dependency):
                self.assertEqual(lock["packages"][f"node_modules/{dependency}"]["version"], version)
