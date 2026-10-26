#!/usr/bin/env python3
"""Validate tag CI provenance or record the identity of a packaged CI image."""

import argparse
import sys
from urllib.parse import quote

if __package__:
    from .contracts import (COMPONENTS, SCHEMA_VERSION, WORKFLOW_PATH, ReleaseError,
                            command_json, image_metadata, require, validate_repository,
                            validate_sha, validate_tag, write_json)
else:
    from contracts import (COMPONENTS, SCHEMA_VERSION, WORKFLOW_PATH, ReleaseError,
                           command_json, image_metadata, require, validate_repository,
                           validate_sha, validate_tag, write_json)


# Set from github.ref_type/ref_name by the integration workflow's run-name.
# REST head_branch does not provide an unambiguous original tag-push ref.
RELEASE_RUN_PREFIX = "Release tag: "


def github_api(path, *, paginate=False):
    arguments = ["gh", "api", "--hostname", "github.com", "-H", "Accept: application/vnd.github+json"]
    if paginate:
        arguments.extend(["--paginate", "--slurp"])
    return command_json([*arguments, path], "GitHub release provenance lookup")


def tag_commit(repository, source_tag):
    validate_repository(repository)
    validate_tag(source_tag)
    reference = github_api(f"repos/{repository}/git/ref/tags/{quote(source_tag, safe='')}")
    require(isinstance(reference, dict) and reference.get("ref") == f"refs/tags/{source_tag}",
            "The source release tag no longer exists.")
    target = reference.get("object", {})
    for _ in range(8):
        require(isinstance(target, dict), "The source tag target is malformed.")
        if target.get("type") == "commit":
            return validate_sha(target.get("sha"))
        require(target.get("type") == "tag", "The source tag does not identify a commit.")
        tag_sha = validate_sha(target.get("sha"))
        annotated = github_api(f"repos/{repository}/git/tags/{tag_sha}")
        require(isinstance(annotated, dict), "The annotated source tag is malformed.")
        target = annotated.get("object", {})
    raise ReleaseError("The annotated source tag nesting is unsupported.")


def verify_run(repository, run_id):
    validate_repository(repository)
    require(type(run_id) is int and run_id > 0, "A positive CI run ID is required.")
    run = github_api(f"repos/{repository}/actions/runs/{run_id}")
    require(isinstance(run, dict) and run.get("id") == run_id,
            "The requested CI run was not identified.")
    require(run.get("event") == "push" and run.get("status") == "completed"
            and run.get("conclusion") == "success", "Release requires a completed successful push CI run.")
    workflow_path = run.get("path")
    require(isinstance(workflow_path, str) and workflow_path.partition("@")[0] == WORKFLOW_PATH,
            "The run used a different CI workflow.")
    require(run.get("repository", {}).get("full_name") == repository
            and run.get("head_repository", {}).get("full_name") == repository,
            "The run source is not the trusted repository.")
    source_sha = validate_sha(run.get("head_sha"))
    title = run.get("display_title")
    require(isinstance(title, str) and title.startswith(RELEASE_RUN_PREFIX),
            "The CI run does not explicitly identify a source tag push.")
    source_tag = validate_tag(title[len(RELEASE_RUN_PREFIX):])
    require(tag_commit(repository, source_tag) == source_sha,
            "The current source tag has moved since the successful CI run.")
    attempt = run.get("run_attempt")
    require(type(attempt) is int and attempt > 0, "The CI run attempt is missing.")

    pages = github_api(f"repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100", paginate=True)
    require(isinstance(pages, list) and pages, "No retained CI artifacts were found.")
    artifacts = []
    for page in pages:
        require(isinstance(page, dict) and isinstance(page.get("artifacts"), list),
                "The CI artifact listing is malformed.")
        artifacts.extend(page["artifacts"])
    selected = {}
    for component in COMPONENTS:
        name = f"{component}-image"
        matches = [artifact for artifact in artifacts if artifact.get("name") == name]
        require(len(matches) == 1, f"Release requires exactly one retained {name} artifact.")
        artifact = matches[0]
        require(artifact.get("expired") is False and type(artifact.get("id")) is int
                and artifact["id"] > 0, f"The {name} artifact has expired or is invalid.")
        provenance = artifact.get("workflow_run", {})
        require(provenance.get("id") == run_id and provenance.get("head_sha") == source_sha,
                f"The {name} artifact source does not match the CI run.")
        selected[component] = {"id": artifact["id"], "name": name}
    return {
        "schema_version": SCHEMA_VERSION,
        "repository": repository,
        "run_id": run_id,
        "run_attempt": attempt,
        "source_sha": source_sha,
        "source_tag": source_tag,
        "artifacts": selected,
    }


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Verify the successful tag CI and retained image artifacts")
    run.add_argument("--run-id", required=True, type=int)
    run.add_argument("--repository", required=True)
    run.add_argument("--output", required=True)
    image = commands.add_parser("image-metadata", help="Record verified packaged image identity")
    image.add_argument("--image", required=True)
    image.add_argument("--component", required=True, choices=COMPONENTS)
    image.add_argument("--source-sha", required=True)
    image.add_argument("--source-version", required=True)
    image.add_argument("--output", required=True)
    options = parser.parse_args(arguments)
    try:
        if options.command == "run":
            result = verify_run(options.repository, options.run_id)
        else:
            result = image_metadata(options.image, options.component, options.source_sha, options.source_version)
        write_json(options.output, result)
    except ReleaseError as exc:
        parser.exit(1, f"Release verification refused: {exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
