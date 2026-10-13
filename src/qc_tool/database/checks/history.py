"""Keep the draft free of migrations; establish history at the release freeze."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib


from qc_tool.database.policy import baseline_paths
from qc_tool.database.policy import DatabasePolicyError
from qc_tool.database.policy import SOURCE_DIRECTORY
from qc_tool.database.policy import MIGRATIONS_DIRECTORY
from qc_tool.database.policy import load_policy
from qc_tool.database.policy import parse_policy
from qc_tool.database.policy import POLICY_PATH


MigrationHistoryError = DatabasePolicyError

CORRECTION_PATH = "src/qc_tool/database/history_corrections/3.0.0-models-only.json"
UNPUBLISHED_FREEZE_CORRECTION = {
    "schema_version": 1,
    "operation": "withdraw_unpublished_3.0.0_schema_freeze",
    "release_version": "3.0.0",
    "comparison_commit": "41a1427f47ce8e8068ac6605d6bc17377309a69c",
    "publication_state": "unpublished",
    "previous_policy": {
        "phase": "released",
        "baselines": {"accounts": "0001_major_release", "dashboard": "0001_major_release"},
    },
    "corrected_policy": {"phase": "draft", "baselines": {}},
    "removed_migrations": {
        "src/qc_tool/database/migrations/accounts/0001_major_release.py":
            "87b395b196f810718285ccd16fcc0ad9e793b57aca5fa402950aa01d25113b7a",
        "src/qc_tool/database/migrations/dashboard/0001_major_release.py":
            "bb9c2c77ed9be6d93c107f1ba141cffbc2cc6206ae708d4b6a2a0e0d081f458c",
        "src/qc_tool/database/migrations/dashboard/0002_legacy_submission_filename_index.py":
            "3ae5b166b6eaf63754601093f1edd99074884e25ec5e7bdeb2088ba576143b56",
    },
}


def _project_version(repository, base=None):
    path = repository / "pyproject.toml"
    if base is None and not path.exists():
        return None
    if base is None and (not path.is_file() or path.is_symlink()):
        raise MigrationHistoryError("The project version must come from a regular pyproject.toml file.")
    try:
        body = _git(repository, "show", f"{base}:pyproject.toml") if base else path.read_bytes()
        version = tomllib.loads(body.decode("utf-8"))["project"]["version"]
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError) as error:
        raise MigrationHistoryError("Cannot read the project version from pyproject.toml.") from error
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:[A-Za-z0-9.+-]+)?", version):
        raise MigrationHistoryError("The project version must identify its major, minor and patch release.")
    return version


def _require_migration_version(repository):
    version = _project_version(repository)
    if version is None or tuple(map(int, re.match(r"(\d+)\.(\d+)\.(\d+)", version).groups())) < (3, 0, 1):
        raise MigrationHistoryError("Migration definitions and the first schema freeze require version 3.0.1 or later.")


def _correction_bytes(repository):
    path = repository / CORRECTION_PATH
    parts = Path(CORRECTION_PATH).parts
    ancestors = [repository.joinpath(*parts[:index]) for index in range(1, len(parts))]
    if not path.is_file() or any(part.is_symlink() for part in (path, *ancestors)):
        raise MigrationHistoryError("The history correction audit must be a regular, nonsymlink file.")
    try:
        return path.read_bytes()
    except OSError as error:
        raise MigrationHistoryError("Cannot read the history correction audit.") from error


def _unique_correction_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise MigrationHistoryError("The history correction audit contains duplicate JSON keys.")
        result[key] = value
    return result


def _check_unpublished_correction(repository, base, base_policy, policy, base_files, proposed_files):
    expected = UNPUBLISHED_FREEZE_CORRECTION
    if base != expected["comparison_commit"] or CORRECTION_PATH in base_files:
        raise MigrationHistoryError("Released migration history cannot return to the draft phase; only the exact unpublished correction base is eligible.")
    if base_policy != expected["previous_policy"] or policy != expected["corrected_policy"]:
        raise MigrationHistoryError("The unpublished correction must match its exact previous and corrected policies.")
    if _project_version(repository) != "3.0.0" or _project_version(repository, base) != "3.0.0":
        raise MigrationHistoryError("The unpublished history correction applies only to version 3.0.0.")
    try:
        document = json.loads(_correction_bytes(repository), object_pairs_hook=_unique_correction_keys)
    except (ValueError, UnicodeDecodeError) as error:
        raise MigrationHistoryError("The history correction audit must contain valid JSON.") from error
    if not isinstance(document, dict) or type(document.get("schema_version")) is not int or document != expected:
        raise MigrationHistoryError("The history correction audit does not match the reviewed unpublished release contract.")
    definitions = {path for path in base_files if path.startswith(SOURCE_DIRECTORY + "/") and _is_migration_definition(path)}
    if definitions != set(expected["removed_migrations"]):
        raise MigrationHistoryError("The unpublished comparison contains unreviewed migration definitions.")
    for path, digest in expected["removed_migrations"].items():
        if hashlib.sha256(_git(repository, "show", f"{base}:{path}")).hexdigest() != digest:
            raise MigrationHistoryError("The unpublished comparison migration bytes differ from the reviewed hashes.")
    _require_no_draft_files(proposed_files)
    return "Unpublished 3.0.0 correction: removed the reviewed freeze; draft models define the schema. Audit retained."


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
    immutable and new migration files are allowed. One pinned, audited correction
    withdraws the unpublished 3.0.0 freeze; there is no reset override.
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
    correction_present = (repository / CORRECTION_PATH).exists() or (repository / CORRECTION_PATH).is_symlink()
    if CORRECTION_PATH in base_files:
        if _correction_bytes(repository) != _git(repository, "show", f"{base}:{CORRECTION_PATH}"):
            raise MigrationHistoryError("The committed history correction audit is immutable.")
    if POLICY_PATH not in base_files:
        if correction_present:
            raise MigrationHistoryError("A history correction audit cannot accompany policy introduction.")
        if policy["phase"] != "draft":
            raise MigrationHistoryError(
                "The first database policy must introduce a draft schema; "
                "release freeze must be a later change."
            )
        _require_no_draft_files(proposed_files)
        return "Draft policy introduction: legacy history removed; models define the schema."

    base_policy = parse_policy(_git(repository, "show", f"{base}:{POLICY_PATH}"))
    if base_policy["phase"] == "released" and policy["phase"] != "released":
        return _check_unpublished_correction(repository, base, base_policy, policy, base_files, proposed_files)
    if correction_present and CORRECTION_PATH not in base_files:
        raise MigrationHistoryError("The audit record may be introduced only with the exact unpublished 3.0.0 correction.")
    if policy["phase"] == "draft":
        _require_no_draft_files(proposed_files)
        return "Draft phase: no migration files; models may evolve freely."

    _require_baselines(proposed_files, baselines, "the proposed source")
    _require_migration_version(repository)
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
