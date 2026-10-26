"""Small, shared validation contracts for trusted CI image handoff."""

import json
from pathlib import Path
import re
import subprocess


SCHEMA_VERSION = 1
WORKFLOW_PATH = ".github/workflows/integration-tests.yml"
IMAGE_REPOSITORIES = {
    "frontend": "eeacms/copernicus-qctool-frontend",
    "worker": "eeacms/copernicus-qctool-worker",
}
COMPONENTS = tuple(IMAGE_REPOSITORIES)


class ReleaseError(ValueError):
    """Refuse an ambiguous or unsafe release without exposing command output."""


def require(condition, message):
    if not condition:
        raise ReleaseError(message)


def command(arguments, description):
    try:
        return subprocess.run(
            arguments, check=True, capture_output=True, text=True, timeout=900,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReleaseError(f"{description} failed; inspect the release state before retrying.") from exc


def command_json(arguments, description):
    try:
        return json.loads(command(arguments, description))
    except json.JSONDecodeError as exc:
        raise ReleaseError(f"{description} returned invalid JSON.") from exc


def read_json(path):
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseError("Cannot read valid release metadata.") from exc
    require(isinstance(value, dict), "Release metadata must be a JSON object.")
    return value


def write_json(path, value):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def validate_sha(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value),
            "The source revision must be a full lowercase commit SHA.")
    return value


def validate_digest(value):
    require(isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value),
            "An image ID or manifest digest is invalid.")
    return value


def validate_repository(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value),
            "The source repository must be an owner/name pair.")
    return value


def validate_tag(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", value)
            and value.lower() != "latest", "The source tag is not a supported immutable image tag.")
    return value


def inspect_image(image):
    inspected = command_json(["docker", "image", "inspect", image], "Local image inspection")
    require(isinstance(inspected, list) and len(inspected) == 1,
            "Local image inspection did not identify exactly one image.")
    result = inspected[0]
    require(isinstance(result, dict), "Local image inspection is malformed.")
    return result


def image_metadata(image, component, source_sha, source_version):
    require(component in COMPONENTS, "Unknown release component.")
    validate_sha(source_sha)
    require(isinstance(source_version, str) and source_version, "The source version is missing.")
    inspected = inspect_image(image)
    labels = inspected.get("Config", {}).get("Labels") or {}
    require(labels.get("org.opencontainers.image.revision") == source_sha,
            "The packaged image revision does not match the CI source.")
    require(labels.get("org.opencontainers.image.version") == source_version,
            "The packaged image version does not match the CI source.")
    require(inspected.get("Os") == "linux" and inspected.get("Architecture") == "amd64",
            "Release image platform must be linux/amd64.")
    return {
        "schema_version": SCHEMA_VERSION,
        "component": component,
        "image_id": validate_digest(inspected.get("Id")),
        "source_sha": source_sha,
        "source_version": source_version,
        "platform": "linux/amd64",
    }


def validate_release(value):
    require(value.get("schema_version") == SCHEMA_VERSION, "Unsupported release metadata version.")
    validate_repository(value.get("repository"))
    validate_sha(value.get("source_sha"))
    validate_tag(value.get("source_tag"))
    require(type(value.get("run_id")) is int and value["run_id"] > 0,
            "The trusted CI run identity is missing.")
    require(type(value.get("run_attempt")) is int and value["run_attempt"] > 0,
            "The trusted CI run attempt is missing.")
    return value


def verify_loaded_image(metadata, release, component):
    require(metadata.get("schema_version") == SCHEMA_VERSION, "Unsupported image metadata version.")
    require(metadata.get("component") == component, "The image artifact component is incorrect.")
    require(metadata.get("source_sha") == release["source_sha"],
            "The image artifact belongs to a different source revision.")
    require(metadata.get("source_version") == release["source_tag"],
            "The image artifact belongs to a different source tag.")
    require(metadata.get("platform") == "linux/amd64", "The image artifact platform is unsupported.")
    image_id = validate_digest(metadata.get("image_id"))
    actual = image_metadata(image_id, component, release["source_sha"], release["source_tag"])
    require(actual == metadata, "The loaded image does not match its retained CI metadata.")
    return image_id
