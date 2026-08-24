"""Validation of the bounded S3 object listing returned by a provider."""

from dataclasses import dataclass
import posixpath
import unicodedata

from .errors import rejected_delivery


@dataclass(frozen=True)
class S3Object:
    key: str
    filename: str
    size: int
    etag: object = None


def validate_object_listing(response, *, prefix, policy):
    """Return safe objects belonging to exactly one logical delivery."""

    if not isinstance(response, dict):
        raise rejected_delivery("listing is not a mapping")
    contents = response.get("Contents") or []
    if (
        not isinstance(contents, list)
        or not contents
        or response.get("IsTruncated")
        or len(contents) > policy.max_objects
    ):
        raise rejected_delivery("listing is empty, truncated, or too large")

    objects = []
    normalized_names = set()
    logical_deliveries = set()
    declared_total = 0
    for item in contents:
        if not isinstance(item, dict):
            raise rejected_delivery("object metadata is invalid")
        key = item.get("Key")
        size = item.get("Size")
        if (
            not isinstance(key, str)
            or not key.startswith(prefix)
            or not key.isprintable()
            or "\\" in key
            or unicodedata.normalize("NFC", key) != key
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
        ):
            raise rejected_delivery("object key or size is invalid")

        filename = posixpath.basename(key)
        if not _safe_filename(filename):
            raise rejected_delivery("object filename is unsafe")
        normalized_name = filename.casefold()
        if normalized_name in normalized_names:
            raise rejected_delivery("object filenames collide")
        normalized_names.add(normalized_name)

        delivery_stem = filename.partition(".")[0]
        if not delivery_stem:
            raise rejected_delivery("object has no delivery name")
        logical_deliveries.add(
            posixpath.join(posixpath.dirname(key), delivery_stem).casefold()
        )
        declared_total += size
        if declared_total > policy.max_download_bytes:
            raise rejected_delivery("declared download size exceeds its limit")

        etag = item.get("ETag")
        if etag is not None and (
            not isinstance(etag, str)
            or not etag.isprintable()
            or len(etag) > 256
        ):
            raise rejected_delivery("object ETag is invalid")
        objects.append(S3Object(key, filename, size, etag))

    if len(logical_deliveries) != 1 or declared_total <= 0:
        raise rejected_delivery("listing does not identify one delivery")
    zip_objects = [item for item in objects if item.filename.lower().endswith(".zip")]
    if zip_objects and len(objects) != 1:
        raise rejected_delivery("ZIP deliveries cannot include sidecar objects")
    return tuple(objects)


def _safe_filename(filename):
    if (
        not filename
        or filename in (".", "..")
        or filename != filename.strip()
        or ":" in filename
        or len(filename.encode("utf-8")) > 255
    ):
        return False
    return not any(unicodedata.category(character) in ("Cc", "Cf") for character in filename)
