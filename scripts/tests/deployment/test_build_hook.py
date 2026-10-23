"""Build-hook paths and source identity without starting Docker or services."""

import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest


class BuildHookTests(unittest.TestCase):
    repository = Path(__file__).resolve().parents[3]

    def run_hook(self, *, directory, dockerfile, branch="release/example", commit=None):
        with TemporaryDirectory(prefix="qc-build-hook-test-") as temporary:
            root = Path(temporary)
            log = root / "arguments"
            docker = root / "docker"
            docker.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$QC_BUILD_HOOK_TEST_LOG"\n')
            docker.chmod(0o755)
            environment = {
                **os.environ,
                "PATH": f"{root}:{os.environ.get('PATH', '')}",
                "DOCKERFILE_PATH": dockerfile,
                "IMAGE_NAME": "qc-tool-test/worker:offline",
                "QC_BUILD_HOOK_TEST_LOG": str(log),
            }
            environment.pop("SOURCE_BRANCH", None)
            environment.pop("SOURCE_COMMIT", None)
            if branch is not None:
                environment["SOURCE_BRANCH"] = branch
            if commit is not None:
                environment["SOURCE_COMMIT"] = commit
            result = subprocess.run(
                [str(self.repository / "docker/hooks/build")],
                cwd=directory, env=environment, text=True, capture_output=True,
            )
            arguments = log.read_text().splitlines() if log.exists() else []
        self.assertEqual(result.returncode, 0, result.stderr)
        return arguments

    def test_repository_and_docker_workdirs_select_root_context_and_real_dockerfile(self):
        for directory, filename in (
            (self.repository, "docker/Dockerfile.worker"),
            (self.repository / "docker", "docker/Dockerfile.worker"),
            (self.repository / "docker", "Dockerfile.worker"),
            (self.repository, "Dockerfile.frontend"),
        ):
            with self.subTest(directory=directory, dockerfile=filename):
                arguments = self.run_hook(directory=directory, dockerfile=filename)
                self.assertEqual(arguments[-1], str(self.repository))
                target = Path(arguments[arguments.index("--file") + 1])
                if not target.is_absolute():
                    target = directory / target
                self.assertTrue(target.is_file(), target)
                self.assertEqual(target.parent.resolve(), self.repository / "docker")

    def test_release_tag_and_source_commit_are_passed_separately(self):
        arguments = self.run_hook(
            directory=self.repository, dockerfile="docker/Dockerfile.frontend",
            branch="3.0.0rc1", commit="a" * 40,
        )
        self.assertIn("VERSION=3.0.0rc1", arguments)
        self.assertIn("SOURCE_REVISION=" + "a" * 40, arguments)

    def test_branch_build_keeps_branch_version_and_checkout_revision(self):
        arguments = self.run_hook(
            directory=self.repository, dockerfile="docker/Dockerfile.worker",
        )
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.repository, text=True,
        ).strip()
        self.assertIn("VERSION=release/example", arguments)
        self.assertIn("SOURCE_REVISION=" + revision, arguments)

    def test_missing_branch_falls_back_to_source_commit(self):
        arguments = self.run_hook(
            directory=self.repository, dockerfile="docker/Dockerfile.frontend",
            branch=None, commit="b" * 40,
        )
        self.assertIn("VERSION=" + "b" * 40, arguments)
        self.assertIn("SOURCE_REVISION=" + "b" * 40, arguments)

    def test_missing_hub_metadata_uses_checkout_revision(self):
        arguments = self.run_hook(
            directory=self.repository / "docker", dockerfile="Dockerfile.worker",
            branch=None,
        )
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.repository, text=True,
        ).strip()
        self.assertIn("VERSION=" + revision, arguments)
        self.assertIn("SOURCE_REVISION=" + revision, arguments)


if __name__ == "__main__":
    unittest.main()
