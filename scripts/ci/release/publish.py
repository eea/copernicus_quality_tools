#!/usr/bin/env python3
"""Publish loaded, verified CI images without rebuilding or moving existing tags."""

import argparse
import os
from pathlib import Path
import sys

if not __package__:
    # Use only trusted checkout code; downloaded artifacts contain data, never helpers.
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from scripts.ci.release.contracts import (COMPONENTS, IMAGE_REPOSITORIES, ReleaseError, command,
                                              read_json, require, validate_release, verify_loaded_image, write_json)
    from scripts.ci.release.registry import manifest
    from scripts.ci.release.verify import verify_run
else:
    from .contracts import (COMPONENTS, IMAGE_REPOSITORIES, ReleaseError, command,
                            read_json, require, validate_release, verify_loaded_image, write_json)
    from .registry import manifest
    from .verify import verify_run


def assert_destination(component, source_tag, image_id):
    existing = manifest(IMAGE_REPOSITORIES[component], source_tag)
    require(existing is None or existing["image_id"] == image_id,
            f"The {component} release tag already identifies a different image; it will not be moved.")
    return existing


def publish_pair(release, metadata):
    require(os.environ.get("QC_TOOL_IMAGE_PUBLISHER") == "github-actions",
            "GitHub Actions image publication has not been explicitly enabled.")
    validate_release(release)
    require(verify_run(release["repository"], release["run_id"]) == release,
            "The trusted CI run, source tag or retained artifacts changed after release preflight.")
    image_ids = {
        component: verify_loaded_image(metadata[component], release, component)
        for component in COMPONENTS
    }
    # Check both destinations before publishing either component. A matching
    # existing image permits safe retry after a partial previous pair upload.
    for component in COMPONENTS:
        assert_destination(component, release["source_tag"], image_ids[component])
    for component in COMPONENTS:
        existing = assert_destination(component, release["source_tag"], image_ids[component])
        if existing is None:
            destination = f"{IMAGE_REPOSITORIES[component]}:{release['source_tag']}"
            command(["docker", "image", "tag", image_ids[component], destination], "Local release tagging")
            command(["docker", "image", "push", destination], f"{component.capitalize()} image publication")
    # A push response alone does not establish the registry's retained content.
    images = {}
    for component in COMPONENTS:
        retained = assert_destination(component, release["source_tag"], image_ids[component])
        require(retained is not None, f"Docker Hub did not retain the {component} release image.")
        images[component] = {
            "image_id": image_ids[component],
            "tag": f"{IMAGE_REPOSITORIES[component]}:{release['source_tag']}",
            "digest": f"{IMAGE_REPOSITORIES[component]}@{retained['digest']}",
            "platform": "linux/amd64",
        }
    return {**release, "images": images}


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", required=True)
    parser.add_argument("--frontend-metadata", required=True)
    parser.add_argument("--worker-metadata", required=True)
    parser.add_argument("--output", required=True)
    options = parser.parse_args(arguments)
    try:
        release = read_json(options.release)
        metadata = {
            component: read_json(getattr(options, f"{component}_metadata"))
            for component in COMPONENTS
        }
        result = publish_pair(release, metadata)
        write_json(options.output, result)
        for component in COMPONENTS:
            print(f"{component}: {result['images'][component]['digest']}")
    except ReleaseError as exc:
        parser.exit(1, f"Image publication refused: {exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
