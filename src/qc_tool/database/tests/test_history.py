import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from qc_tool.database.checks.history import baseline_paths
from qc_tool.database.checks.history import check_migration_history
from qc_tool.database.checks.history import MigrationHistoryError
from qc_tool.database.checks.history import parse_policy
from qc_tool.database.checks.history import POLICY_PATH


BASELINE_NAMES = {"accounts": "0001_major_release", "dashboard": "0001_major_release"}
BASELINES = baseline_paths({"baselines": BASELINE_NAMES})


class MigrationHistoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repository = Path(self.directory.name)
        self.git("init", "--quiet")

    def git(self, *arguments):
        return subprocess.run(
            ["git", "-C", str(self.repository), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()

    def write(self, path, content="baseline\n"):
        target = self.repository / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def policy(self, phase="draft", baselines=None):
        self.write(POLICY_PATH, json.dumps({
            "phase": phase,
            "baselines": (BASELINE_NAMES if phase == "released" else {}) if baselines is None else baselines,
        }))

    def commit(self):
        self.git("add", ".")
        self.git(
            "-c", "user.name=Migration test",
            "-c", "user.email=migration-test@example.invalid",
            "-c", "commit.gpgsign=false",
            "commit", "--quiet", "--allow-empty", "-m", "comparison base",
        )
        return self.git("rev-parse", "HEAD")

    def established_baseline(self, phase="draft"):
        self.policy(phase)
        if phase == "released":
            for path in BASELINES:
                self.write(path)
        return self.commit()

    def test_policy_introduction_removes_legacy_history(self):
        old_path = Path(BASELINES[1]).with_name("0001_initial.py")
        self.write(old_path, "legacy schema\n")
        base = self.commit()
        (self.repository / old_path).unlink()
        self.policy()
        self.assertIn("introduction", check_migration_history(self.repository, base))

    def test_policy_introduction_cannot_skip_draft(self):
        base = self.commit()
        self.established_baseline("released")
        with self.assertRaisesRegex(MigrationHistoryError, "first database policy"):
            check_migration_history(self.repository, base)

    def test_draft_models_can_change_without_migration_files(self):
        base = self.established_baseline()
        self.write("src/qc_tool/frontend/dashboard/domain/models.py", "new model schema\n")
        self.assertIn("models may evolve freely", check_migration_history(self.repository, base))

    def test_draft_rejects_new_definitions_in_every_app(self):
        base = self.established_baseline()
        for path in (
            Path(BASELINES[1]).with_name("0002_add_release_notes.py"),
            "src/qc_tool/database/migrations/future_app/0001_initial.py",
            "src/qc_tool/database/migrations/accounts/helpers.py",
        ):
            with self.subTest(path=path):
                self.write(path)
                with self.assertRaisesRegex(MigrationHistoryError, "no migration files"):
                    check_migration_history(self.repository, base)
                (self.repository / path).unlink()

    def test_released_baselines_are_required_in_proposed_source(self):
        base = self.established_baseline("released")
        for path in BASELINES:
            with self.subTest(path=path):
                (self.repository / path).unlink()
                with self.assertRaisesRegex(MigrationHistoryError, "Policy baselines"):
                    check_migration_history(self.repository, base)
                self.write(path)

    def test_migrations_cannot_return_to_component_directories(self):
        path = "src/qc_tool/frontend/accounts/migrations/0002_scattered.py"
        for phase in ("draft", "released"):
            with self.subTest(phase=phase):
                base = self.established_baseline(phase)
                self.write(path)
                with self.assertRaisesRegex(MigrationHistoryError, "must live under"):
                    check_migration_history(self.repository, base)
                (self.repository / path).unlink()

    def test_partial_baseline_in_comparison_base_fails(self):
        self.policy("released")
        self.write(BASELINES[0])
        base = self.commit()
        self.write(BASELINES[1])
        with self.assertRaisesRegex(MigrationHistoryError, "comparison commit"):
            check_migration_history(self.repository, base)

    def test_release_freeze_introduces_initial_snapshots(self):
        base = self.established_baseline()
        self.policy("released")
        for path in BASELINES:
            self.write(path)
        self.assertIn("Release freeze", check_migration_history(self.repository, base))

    def test_release_freeze_requires_all_declared_snapshots(self):
        base = self.established_baseline()
        self.policy("released")
        self.write(BASELINES[0])
        with self.assertRaisesRegex(MigrationHistoryError, "Policy baselines"):
            check_migration_history(self.repository, base)

    def test_release_freeze_cannot_include_incremental_migrations(self):
        base = self.established_baseline()
        self.policy("released")
        for path in BASELINES:
            self.write(path)
        self.write(Path(BASELINES[1]).with_name("0002_add_release_notes.py"))
        with self.assertRaisesRegex(MigrationHistoryError, "only the policy baselines"):
            check_migration_history(self.repository, base)

    def test_released_history_cannot_return_to_draft(self):
        base = self.established_baseline("released")
        self.policy("draft")
        with self.assertRaisesRegex(MigrationHistoryError, "cannot return"):
            check_migration_history(self.repository, base)

    def test_released_baseline_mapping_cannot_change(self):
        base = self.established_baseline("released")
        renamed = dict(BASELINE_NAMES, accounts="0001_renamed")
        self.policy("released", renamed)
        path = Path(BASELINES[0])
        (self.repository / path).rename(self.repository / path.with_name("0001_renamed.py"))
        with self.assertRaisesRegex(MigrationHistoryError, "mapping cannot change"):
            check_migration_history(self.repository, base)

    def test_new_migrations_are_allowed_after_release(self):
        base = self.established_baseline("released")
        self.write(Path(BASELINES[1]).with_name("0002_add_release_notes.py"))
        self.write("src/qc_tool/database/migrations/future_app/0001_initial.py")
        self.assertIn("additions are allowed", check_migration_history(self.repository, base))

    def test_published_baseline_cannot_be_edited(self):
        base = self.established_baseline("released")
        self.write(BASELINES[0], "rewritten schema\n")
        with self.assertRaisesRegex(MigrationHistoryError, "immutable"):
            check_migration_history(self.repository, base)

    def test_later_migration_in_any_app_cannot_be_edited_or_deleted(self):
        self.established_baseline("released")
        later_path = "src/qc_tool/database/migrations/future_app/0001_initial.py"
        self.write(later_path)
        base = self.commit()
        self.write(later_path, "rewritten schema\n")
        with self.assertRaisesRegex(MigrationHistoryError, "immutable"):
            check_migration_history(self.repository, base)
        (self.repository / later_path).unlink()
        with self.assertRaisesRegex(MigrationHistoryError, "immutable"):
            check_migration_history(self.repository, base)

    def test_package_initializers_can_change_in_both_phases(self):
        for phase in ("draft", "released"):
            with self.subTest(phase=phase):
                for path in BASELINES:
                    self.write(Path(path).with_name("__init__.py"), "")
                base = self.established_baseline(phase)
                self.write(Path(BASELINES[0]).with_name("__init__.py"), '"""Migrations."""\n')
                check_migration_history(self.repository, base)

    def test_symlink_cannot_replace_a_baseline(self):
        base = self.established_baseline("released")
        first, second = (self.repository / path for path in BASELINES)
        first.unlink()
        first.symlink_to(second)
        with self.assertRaisesRegex(MigrationHistoryError, "symlinks"):
            check_migration_history(self.repository, base)

    def test_policy_cannot_be_removed_or_replaced_with_symlink(self):
        base = self.established_baseline()
        policy = self.repository / POLICY_PATH
        original = policy.read_bytes()
        policy.unlink()
        with self.assertRaisesRegex(MigrationHistoryError, "regular file"):
            check_migration_history(self.repository, base)
        self.write("other_policy.json", original.decode())
        policy.symlink_to(self.repository / "other_policy.json")
        with self.assertRaisesRegex(MigrationHistoryError, "regular file"):
            check_migration_history(self.repository, base)

    def test_missing_zero_and_unknown_comparison_bases_fail(self):
        self.established_baseline()
        for base in ("", "HEAD", "0" * 40, "f" * 40):
            with self.subTest(base=base):
                with self.assertRaises(MigrationHistoryError):
                    check_migration_history(self.repository, base)


class PolicyValidationTests(unittest.TestCase):
    def test_valid_policy(self):
        for policy in (
            {"phase": "draft", "baselines": {}},
            {"phase": "released", "baselines": BASELINE_NAMES},
            {"phase": "released", "baselines": {"qc_database": "0001_major_release"}},
        ):
            self.assertEqual(parse_policy(json.dumps(policy)), policy)

    def test_invalid_or_ambiguous_policy_fails(self):
        for policy in (
            "{",
            "[]",
            json.dumps({"phase": "released", "baselines": {}}),
            json.dumps({"phase": "released", "baselines": {"../app": "0001_initial"}}),
            json.dumps({"phase": "released", "baselines": {"accounts": "0002_later"}}),
            '{"phase":"draft","phase":"released","baselines":{}}',
            json.dumps({"phase": "draft", "baselines": BASELINE_NAMES, "reset": True}),
            json.dumps({"phase": "unknown", "baselines": BASELINE_NAMES}),
            json.dumps({"phase": [], "baselines": BASELINE_NAMES}),
            json.dumps({"phase": "draft", "baselines": {"accounts": "0001_major_release"}}),
            json.dumps({"phase": "draft", "baselines": dict(BASELINE_NAMES, accounts="../escape")}),
            json.dumps({"phase": "draft", "baselines": dict(BASELINE_NAMES, accounts=None)}),
        ):
            with self.subTest(policy=policy):
                with self.assertRaises(MigrationHistoryError):
                    parse_policy(policy)


if __name__ == "__main__":
    unittest.main()
