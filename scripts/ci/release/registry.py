"""Read public Docker Hub manifests, distinguishing absence from lookup failure."""

import hashlib
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .contracts import IMAGE_REPOSITORIES, ReleaseError, require, validate_digest, validate_tag


MANIFEST_TYPES = ", ".join((
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
))
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


def response_json(response):
    data = response.read(MAX_RESPONSE_BYTES + 1)
    require(len(data) <= MAX_RESPONSE_BYTES, "The registry response exceeds the metadata limit.")
    try:
        result = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseError("The registry returned invalid metadata.") from exc
    require(isinstance(result, dict), "The registry metadata is malformed.")
    return data, result


def manifest(repository, tag):
    """Return verified config/manifest digests, or None for explicit absence only."""
    require(repository in IMAGE_REPOSITORIES.values(), "The registry destination is unsupported.")
    validate_tag(tag)
    query = urlencode({"service": "registry.docker.io", "scope": f"repository:{repository}:pull"})
    try:
        with urlopen("https://auth.docker.io/token?" + query, timeout=30) as response:
            _, authorization = response_json(response)
        token = authorization.get("token")
        require(isinstance(token, str) and token, "Docker Hub did not authorize public manifest inspection.")
        request = Request(
            f"https://registry-1.docker.io/v2/{repository}/manifests/{tag}",
            headers={"Authorization": "Bearer " + token, "Accept": MANIFEST_TYPES},
        )
        try:
            with urlopen(request, timeout=30) as response:
                raw, result = response_json(response)
                digest = validate_digest(response.headers.get("Docker-Content-Digest"))
        except HTTPError as exc:
            if exc.code == 404:
                _, result = response_json(exc)
                errors = result.get("errors")
                if (isinstance(errors, list) and errors
                        and all(isinstance(error, dict) and error.get("code") == "MANIFEST_UNKNOWN"
                                for error in errors)):
                    return None
            raise ReleaseError("Docker Hub manifest inspection failed; refusing to overwrite a tag.") from exc
    except (OSError, URLError) as exc:
        raise ReleaseError("Docker Hub could not be inspected; refusing to publish.") from exc
    require(digest == "sha256:" + hashlib.sha256(raw).hexdigest(),
            "Docker Hub manifest digest does not match its contents.")
    require(result.get("schemaVersion") == 2 and isinstance(result.get("config"), dict),
            "The existing tag is not a supported single-platform image manifest.")
    return {"digest": digest, "image_id": validate_digest(result["config"].get("digest"))}
