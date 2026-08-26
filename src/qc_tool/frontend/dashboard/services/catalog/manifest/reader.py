"""Bounded UTF-8 JSON reading for product catalog manifests."""

import json
from pathlib import Path

from ..errors import CatalogError


def read_manifest_document(path, *, maximum_bytes):
    manifest_path = Path(path)
    try:
        payload = manifest_path.read_bytes()
    except OSError as exc:
        raise CatalogError(
            "manifest_unavailable",
            "The product catalog manifest cannot be read.",
        ) from exc
    if len(payload) > maximum_bytes:
        raise CatalogError(
            "manifest_too_large",
            "The product catalog manifest exceeds the size limit.",
        )
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CatalogError(
            "invalid_manifest",
            "The product catalog manifest is not valid UTF-8 JSON.",
        ) from exc
