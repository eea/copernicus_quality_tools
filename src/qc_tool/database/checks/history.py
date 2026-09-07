"""Keep the draft free of migrations; establish history at the release freeze."""

import argparse
from pathlib import Path
import re
import subprocess
import sys


from qc_tool.database.policy import baseline_paths
from qc_tool.database.policy import DatabasePolicyError
from qc_tool.database.policy import SOURCE_DIRECTORY
from qc_tool.database.policy import MIGRATIONS_DIRECTORY
from qc_tool.database.policy import load_policy
from qc_tool.database.policy import parse_policy
from qc_tool.database.policy import POLICY_PATH


MigrationHistoryError = DatabasePolicyError


def _is_migration_definition(path):
    relative = Path(path).relative_to(SOURCE_DIRECTORY)
    return (
        "migrations" in relative.parts[:-1]
        and relative.suffix == ".py"
        and relative.name != "__init__.py"
    )


def _proposed_migrations(repository):
    result = set()
    for path in (repository / SOURCE_DIRECTORY).rglob("*"):
        relative = path.relative_to(repository).as_posix()
        if "migrations" not in Path(relative).parts:
            continue
        if path.is_symlink():
            raise MigrationHistoryError(f"Migration paths must not be symlinks: {relative}.")
        if path.is_file() and _is_migration_definition(relative):
            if not relative.startswith(MIGRATIONS_DIRECTORY + "/"):
                raise MigrationHistoryError(
                    f"Migration definitions must live under {MIGRATIONS_DIRECTORY}: {relative}."
                )
            result.add(relative)
    return result


def _require_baselines(files, baselines, location):
    missing = sorted(set(baselines).difference(files))
    if missing:
        raise MigrationHistoryError(
            f"Policy baselines must be present in {location}: " + ", ".join(missing)
        )


def _require_no_draft_files(files):
    if files:
        raise MigrationHistoryError(
            "Draft phase has no migration files; change models directly: "
            + ", ".join(sorted(files))
        )


def _git(repository, *arguments):
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise MigrationHistoryError(
            "Cannot read the comparison commit; fetch the full Git history "
            "and supply the PR base SHA or push before SHA."
        ) from error
    return result.stdout


def check_migration_history(repository, base):
    """Compare the proposed working tree with an explicit CI comparison SHA.

    Draft models evolve without migration files. The explicit release freeze
    introduces initial snapshots and policy together; afterwards history is
    immutable and new migration files are allowed. There is no reset override.
    """

    repository = Path(repository)
    if not re.fullmatch(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", base or ""):
        raise MigrationHistoryError("An explicit comparison commit SHA is required.")
    if not base.strip("0"):
        raise MigrationHistoryError(
            "An all-zero push before SHA is not a comparison commit; "
            "validate this change through a pull request with an existing base."
        )
    _git(repository, "rev-parse", "--verify", f"{base}^{{commit}}")

    policy = load_policy(repository)
    baselines = baseline_paths(policy)
    proposed_files = _proposed_migrations(repository)

    base_files = {
        path.decode("utf-8")
        for path in _git(
            repository,
            "ls-tree",
            "-r",
            "--name-only",
            "-z",
            base,
            "--",
            SOURCE_DIRECTORY,
            POLICY_PATH,
        ).split(b"\0")
        if path
    }
    if POLICY_PATH not in base_files:
        if policy["phase"] != "draft":
            raise MigrationHistoryError(
                "The first database policy must introduce a draft schema; "
                "release freeze must be a later change."
            )
        _require_no_draft_files(proposed_files)
        return "Draft policy introduction: legacy history removed; models define the schema."

    base_policy = parse_policy(_git(repository, "show", f"{base}:{POLICY_PATH}"))
    if base_policy["phase"] == "released" and policy["phase"] != "released":
        raise MigrationHistoryError(
            "Released migration history cannot return to the draft phase."
        )
    if policy["phase"] == "draft":
        _require_no_draft_files(proposed_files)
        return "Draft phase: no migration files; models may evolve freely."

    _require_baselines(proposed_files, baselines, "the proposed source")
    if base_policy["phase"] == "draft":
        if proposed_files != set(baselines):
            raise MigrationHistoryError("Release freeze must introduce only the policy baselines.")
        return "Release freeze: initial schema snapshots establish immutable history."
    if policy["baselines"] != base_policy["baselines"]:
        raise MigrationHistoryError("The established database baseline mapping cannot change.")

    protected = {
        path
        for path in base_files
        if path.startswith(SOURCE_DIRECTORY + "/") and _is_migration_definition(path)
    }
    _require_baselines(protected, baselines, "the comparison commit")

    changed = []
    for path in sorted(protected):
        proposed = repository / path
        if (
            not proposed.is_file()
            or proposed.is_symlink()
            or proposed.read_bytes() != _git(repository, "show", f"{base}:{path}")
        ):
            changed.append(path)
    if changed:
        raise MigrationHistoryError(
            "Committed migration files are immutable; add a new migration instead: "
            + ", ".join(changed)
        )
    return f"Released phase: preserved {len(protected)} migration files; additions are allowed."


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="PR base SHA or push before SHA")
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    arguments = parser.parse_args(argv)
    try:
        message = check_migration_history(arguments.repository, arguments.base)
    except MigrationHistoryError as error:
        print(f"Migration history check failed: {error}", file=sys.stderr)
        return 1
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
