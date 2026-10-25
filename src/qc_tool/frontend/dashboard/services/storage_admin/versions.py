"""Read-only presentation of the version stores already owned by the application.

This inventory does not introduce a second version database. Boundary pointers
and specification activation markers determine runtime selection; catalog
records add human-readable revision metadata when the database is available.
Only directory metadata and bounded activation markers are read here. Original
specification and boundary bytes are opened by the ordinary storage downloads.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
import re
import stat

from django.db import DatabaseError

from qc_tool.common import CONFIG
from qc_tool.product_security import canonical_product_ident, normalize_product_ident
from qc_tool.frontend.dashboard.services.boundaries.contracts import LIVE_DIRECTORY_NAMES
from qc_tool.frontend.dashboard.services.boundaries.layout import (
    CURRENT_POINTER_NAME, GENERATIONS_DIRECTORY_NAME, current_pointer_target,
    validate_generation_id,
)
from qc_tool.frontend.dashboard.services.boundaries.errors import BoundaryPackageError

from . import files


MAX_SCAN_ENTRIES = 10_000
MAX_MARKER_BYTES = 1024
MAX_CATALOG_ROWS = 10_000
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_STATUS_LABELS = {
    "current": "Current", "previous": "Previous", "archived": "Archived",
    "unknown": "Current version unknown", "unavailable": "Unavailable",
}


class _Inventory:
    def __init__(self):
        self.entries, self.warnings = [], []
        self.scanned_count, self.skipped_count, self.scan_limited = 0, 0, False

    def warn(self, message):
        if message not in self.warnings and len(self.warnings) < 10:
            self.warnings.append(message)

    def scan(self, descriptor):
        result = []
        with os.scandir(descriptor) as iterator:
            for entry in iterator:
                if self.scanned_count >= MAX_SCAN_ENTRIES:
                    self.scan_limited = True
                    break
                self.scanned_count += 1
                try:
                    result.append((entry.name, entry.stat(follow_symlinks=False)))
                except OSError:
                    self.skipped_count += 1
        return sorted(result, key=lambda item: item[0])


@contextmanager
def _directory(parent, name):
    descriptor = os.open(name, files._DIRECTORY_FLAGS, dir_fd=parent)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def _date(status):
    try:
        return datetime.fromtimestamp(status.st_mtime, timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def _status_label(status, *, versioned=True):
    # An unselected installed file has no established content revision. Its
    # presence alone cannot establish that it is an earlier specification.
    return "Not selected" if not versioned and status == "previous" else _STATUS_LABELS[status]


def _row(*, resource, title, version_id, source, area, path, kind, status,
         file_status=None, available=True, message="", product_ident="", **extra):
    source_kind = extra.pop("source_kind", "boundary" if resource == "boundaries" else "saved")
    versioned = (resource == "boundaries" or source_kind in {"activation", "catalog"}
                 or bool(_DIGEST.fullmatch(version_id)))
    location = {"area": area, "path": path, "kind": kind, "source": source,
                "source_kind": source_kind}
    return {
        "resource": resource, "title": title, "product_ident": product_ident, "product_name": "",
        "version_id": version_id, "status": status,
        "version_label": ("SHA-256 " + version_id[:12] if _DIGEST.fullmatch(version_id)
                          else "Original installed file" if version_id.startswith("original:")
                          else "Original installation" if version_id == "legacy-unmanaged"
                          else "Boundary version " + version_id.split("-", 1)[-1][:12]
                          if resource == "boundaries" else "Stored version"),
        "status_label": _status_label(status, versioned=versioned), "source": source,
        "source_kind": source_kind, "versioned": versioned,
        "locations": (location,) if available else (), "location_count": int(available),
        "area": area, "path": path, "kind": kind,
        "modified_at": _date(file_status) if file_status else None,
        "size_bytes": file_status.st_size if file_status and kind == "file" else None,
        "available": available, "message": message,
        "selection_paths": (path,) if available else (),
        "description": "", "imported_at": None, "revision_labels": (),
        "catalog_only": False, "catalog_is_current": None, "catalog_status_label": "",
        **extra,
    }


def _boundary_generation(inventory, generation_id, status, file_status):
    path = GENERATIONS_DIRECTORY_NAME + "/" + generation_id
    available = True
    try:
        with files.directory_descriptor("boundaries", files._parts("boundaries", path)) as directory:
            for name in LIVE_DIRECTORY_NAMES:
                with _directory(directory, name):
                    pass
    except (OSError, files.StorageError):
        available = False
    inventory.entries.append(_row(
        resource="boundaries", title="Boundary package", version_id=generation_id,
        source="Uploaded boundary package" if generation_id.startswith("gen-") else "Retained original boundaries",
        area="boundaries", path=path, kind="directory",
        status=status if available else "unavailable", file_status=file_status,
        available=available,
        message="" if available else "This retained version is incomplete or unavailable. Its files cannot be opened safely.",
    ))


def _boundaries(inventory):
    try:
        with files.root_descriptor("boundaries") as root:
            current, pointer_valid, pointer_present = None, True, True
            try:
                pointer_status = os.stat(CURRENT_POINTER_NAME, dir_fd=root, follow_symlinks=False)
                if not stat.S_ISLNK(pointer_status.st_mode):
                    raise ValueError("not a pointer")
                target = os.readlink(CURRENT_POINTER_NAME, dir_fd=root)
                pieces = target.split("/")
                if len(pieces) != 2:
                    raise ValueError("not a generation")
                current = validate_generation_id(pieces[1])
                if target != current_pointer_target(current):
                    raise ValueError("not canonical")
            except FileNotFoundError:
                pointer_present = False
            except (OSError, ValueError, BoundaryPackageError):
                current, pointer_valid = None, False
                inventory.warn("The current boundary version cannot be determined because its activation pointer is invalid.")

            if not pointer_present:
                try:
                    for name in LIVE_DIRECTORY_NAMES:
                        with _directory(root, name):
                            pass
                except OSError:
                    inventory.warn("No complete current boundary package is available.")
                else:
                    inventory.entries.append(_row(
                        resource="boundaries", title="Original boundary files",
                        version_id="legacy-unmanaged", source="Original installation files",
                        area="boundaries", path="", kind="directory", status="current",
                        file_status=os.fstat(root), selection_paths=LIVE_DIRECTORY_NAMES,
                        message="These original files are current. This installation has no managed version pointer for them.",
                    ))

            seen_current = False
            try:
                with _directory(root, GENERATIONS_DIRECTORY_NAME) as generations:
                    for name, item_status in inventory.scan(generations):
                        try:
                            validate_generation_id(name)
                        except BoundaryPackageError:
                            inventory.skipped_count += 1
                            continue
                        selected = name == current
                        seen_current = seen_current or selected
                        status = "current" if selected else "previous" if pointer_valid else "unknown"
                        _boundary_generation(inventory, name, status, item_status)
            except FileNotFoundError:
                pass
            except OSError:
                inventory.warn("Retained boundary versions are unavailable or contain an unsafe directory link.")
            if current and not seen_current and not inventory.scan_limited:
                inventory.entries.append(_row(
                    resource="boundaries", title="Current boundary package", version_id=current,
                    source="Boundary activation pointer", area="boundaries",
                    path=GENERATIONS_DIRECTORY_NAME + "/" + current, kind="directory",
                    status="unavailable", available=False,
                    message="The activation pointer refers to a boundary version that is missing or unavailable.",
                ))
                inventory.warn("The current boundary package is unavailable. Retained versions have not been activated automatically.")
    except files.StorageError:
        inventory.warn("Boundary storage is not available. Check its configured storage mount.")


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate marker key")
        result[key] = value
    return result


def _read_marker(directory, name, item_status):
    if (not stat.S_ISREG(item_status.st_mode) or item_status.st_nlink != 1
            or item_status.st_size > MAX_MARKER_BYTES):
        raise ValueError("unsafe marker")
    descriptor = os.open(name, files._FILE_FLAGS, dir_fd=directory)
    with os.fdopen(descriptor, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                or opened.st_size > MAX_MARKER_BYTES):
            raise ValueError("unsafe marker")
        payload = handle.read(MAX_MARKER_BYTES + 1)
    if len(payload) > MAX_MARKER_BYTES:
        raise ValueError("oversized marker")
    state = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_keys)
    if not isinstance(state, dict) or type(state.get("active")) is not bool:
        raise ValueError("invalid active marker")
    if state["active"] and (not isinstance(state.get("digest"), str) or not _DIGEST.fullmatch(state["digest"])):
        raise ValueError("invalid digest marker")
    return state


def _specification_states(inventory, root):
    states, complete = {}, True
    try:
        with _directory(root, ".state") as directory:
            for name, item_status in inventory.scan(directory):
                ident = canonical_product_ident(name[:-5]) if name.endswith(".json") else None
                if ident is None:
                    inventory.skipped_count += 1
                    continue
                try:
                    states[ident] = _read_marker(directory, name, item_status)
                except (OSError, ValueError, UnicodeError, RecursionError):
                    states[ident] = None
                    inventory.warn("Some product activation markers are invalid. Their current versions are not inferred from older files.")
    except FileNotFoundError:
        pass
    except OSError:
        complete = False
        inventory.warn("Product activation markers are unavailable. Current specification selection cannot be confirmed.")
    return states, complete and not inventory.scan_limited


def _flat_specifications(inventory, area, source, source_kind):
    rows = []
    try:
        with files.root_descriptor(area) as root:
            for name, item_status in inventory.scan(root):
                ident = normalize_product_ident(name[:-5]) if name.endswith(".json") else None
                if ident is None:
                    continue
                try:
                    files._parts(area, name)
                    entry = files._entry(area, name, item_status)
                    if entry["kind"] != "file":
                        raise ValueError("not a specification file")
                except (files.StorageError, ValueError, OverflowError):
                    inventory.skipped_count += 1
                    continue
                rows.append(_row(
                    resource="specifications", title=ident, product_ident=ident,
                    version_id="original:" + area + ":" + name, source=source, source_kind=source_kind,
                    area=area, path=name, kind="file", status="previous", file_status=item_status,
                    _file_identity=files.entry_fingerprint(item_status),
                    message="Original installed file; its content fingerprint has not been recorded in this inventory.",
                ))
    except files.StorageError:
        inventory.warn(source + " are not available. Check their configured storage mount.")
    return rows


def _specifications(inventory):
    states, states_complete, version_rows = {}, True, []
    try:
        with files.root_descriptor("uploaded-specifications") as root:
            # Markers are scanned first so truncation never silently enables an
            # older deployment source in place of an unread activation marker.
            states, states_complete = _specification_states(inventory, root)
            try:
                with _directory(root, ".versions") as versions:
                    for ident, product_status in inventory.scan(versions):
                        if canonical_product_ident(ident) != ident:
                            inventory.skipped_count += 1
                            continue
                        try:
                            with _directory(versions, ident) as directory:
                                for name, item_status in inventory.scan(directory):
                                    digest = name[:-5] if name.endswith(".json") else ""
                                    if not _DIGEST.fullmatch(digest):
                                        inventory.skipped_count += 1
                                        continue
                                    path = ".versions/" + ident + "/" + name
                                    try:
                                        files._entry("uploaded-specifications", path, item_status)
                                        if not stat.S_ISREG(item_status.st_mode):
                                            raise ValueError("not a specification file")
                                    except (files.StorageError, ValueError, OverflowError):
                                        inventory.skipped_count += 1
                                        continue
                                    marker = states.get(ident)
                                    status = "previous"
                                    if ident in states and marker is None:
                                        status = "unknown"
                                    elif marker is not None:
                                        status = "archived" if not marker["active"] else "current" if marker["digest"] == digest else "previous"
                                    elif not states_complete:
                                        status = "unknown"
                                    version_rows.append(_row(
                                        resource="specifications", title=ident, product_ident=ident,
                                        version_id=digest, digest=digest,
                                        source="Saved original", source_kind="saved", area="uploaded-specifications",
                                        path=path, kind="file", status=status, file_status=item_status,
                                    ))
                        except OSError:
                            inventory.warn("Some retained specification versions are unavailable or unsafe.")
            except FileNotFoundError:
                pass
            except OSError:
                inventory.warn("Retained specification versions are unavailable or contain an unsafe directory link.")
    except files.StorageError:
        # A missing upload root is normal before this installation's first
        # upload. A configured deployment source can still be current.
        upload_root = CONFIG["work_dir"] / "product_definitions"
        if os.path.lexists(upload_root):
            states_complete = False
            inventory.warn("Uploaded specification storage is unavailable. Current specification selection cannot be confirmed.")

    flat_rows = []
    for index, _directory_path in enumerate(CONFIG.get("product_dirs") or ()):
        flat_rows.extend(_flat_specifications(inventory, "spec-" + str(index), "Installed source", "installed"))
    # Uploaded legacy flat files follow deployment directories in runtime
    # precedence, matching common.product_definition_directories().
    if CONFIG["work_dir"] / "product_definitions" not in (CONFIG.get("product_dirs") or ()):
        try:
            with files.root_descriptor("uploaded-specifications"):
                flat_rows.extend(_flat_specifications(inventory, "uploaded-specifications", "Original installed file", "legacy"))
        except files.StorageError:
            pass

    selected = set()
    for row in flat_rows:
        ident, marker = row["product_ident"], states.get(row["product_ident"])
        if (ident in states and marker is None) or not states_complete or inventory.scan_limited:
            row["status"] = "unknown"
        elif marker is not None:
            row["status"] = "previous" if marker["active"] else "archived"
        elif ident not in selected:
            row["status"] = "current"
            selected.add(ident)
        row["status_label"] = _status_label(row["status"], versioned=row["versioned"])

    inventory.entries.extend(version_rows + flat_rows)
    known_versions = {(row["product_ident"], row.get("digest")) for row in version_rows}
    known_version_products = {row["product_ident"] for row in version_rows}
    for ident, marker in states.items():
        if marker is None or (marker["active"] and (ident, marker["digest"]) not in known_versions and not inventory.scan_limited):
            inventory.entries.append(_row(
                resource="specifications", title=ident, product_ident=ident,
                version_id=marker["digest"] if marker else "unknown", source="Specification activation marker", source_kind="activation",
                digest=marker["digest"] if marker else "",
                area="uploaded-specifications", path="", kind="file", status="unavailable", available=False,
                message="The current specification is missing or its activation marker is invalid. An older version has not been selected automatically.",
            ))
        elif not marker["active"] and ident not in known_version_products:
            inventory.entries.append(_row(
                resource="specifications", title=ident, product_ident=ident,
                version_id="archived", source="Specification archive marker", source_kind="activation",
                area="uploaded-specifications", path="", kind="file", status="archived", available=False,
                message="This product is archived. No saved specification version is available in this inventory.",
            ))


def _merge_specification_locations(inventory):
    """One content revision can have several recorded storage locations.

    Digest-addressed originals and catalog records share the application's
    product/digest identity. For flat installed sources we only combine aliases
    of the same observed physical file. A matching name, path in catalog
    provenance, size or modification time is never evidence of equal bytes.
    """
    combined, positions = [], {}
    priority = {"current": 0, "archived": 1, "unknown": 2,
                "previous": 3, "unavailable": 4}
    for row in inventory.entries:
        physical_identity = row.pop("_file_identity", None)
        digest = row.get("digest")
        identity = ((row["product_ident"], "digest", digest) if digest
                    else (row["product_ident"], "physical", physical_identity)
                    if physical_identity else None)
        if identity is None or identity not in positions:
            if identity is not None:
                positions[identity] = len(combined)
            combined.append(row)
            continue
        position = positions[identity]
        previous = combined[position]
        locations = list(previous["locations"])
        for location in row["locations"]:
            if location not in locations:
                locations.append(location)
        # Source precedence was already evaluated by the runtime-compatible
        # scanner. Combining an alias cannot change which version is selected.
        if priority[row["status"]] < priority[previous["status"]]:
            previous = combined[position] = row
        previous["locations"] = tuple(locations)
        previous["location_count"] = len(locations)
    inventory.entries = combined


def _catalog_metadata(inventory):
    """Reconcile retained originals with bounded scalar catalog history.

    A stored database snapshot remains discoverable when its exact original
    file is absent. It is never turned into a downloadable substitute, and a
    same-named deployment file is not assumed to have the catalog fingerprint.
    """
    from qc_tool.frontend.dashboard.models import Product, QcDefinition, ProductReleaseDefinition

    try:
        definitions = list(QcDefinition.objects.order_by("-imported_at", "-pk").values(
            "pk", "product_ident", "digest", "description", "imported_at",
        )[:MAX_CATALOG_ROWS + 1])
        if len(definitions) > MAX_CATALOG_ROWS:
            inventory.warn("Catalog history reached its inventory limit. Some older records may be omitted from this listing.")
        definitions = definitions[:MAX_CATALOG_ROWS]
        idents = sorted({row["product_ident"] for row in inventory.entries + definitions if row["product_ident"]})
        products = dict(Product.objects.filter(ident__in=idents).values_list("ident", "name"))
        definition_map = {(row["product_ident"], row["digest"]): row for row in definitions}
        links = list(ProductReleaseDefinition.objects.filter(qc_definition_id__in=[row["pk"] for row in definitions]).order_by(
            "-product_release__revision", "-pk",
        ).values("qc_definition_id", "product_release__revision", "product_release__release_key", "product_release__is_current")[:MAX_CATALOG_ROWS + 1])
        if len(links) > MAX_CATALOG_ROWS:
            inventory.warn("Some product release references were omitted from this page. The stored version files remain available.")
        release_map = {}
        for link in links[:MAX_CATALOG_ROWS]:
            release_map.setdefault(link["qc_definition_id"], []).append(link)
        known_versions = {(row["product_ident"], row.get("digest")) for row in inventory.entries if row.get("digest")}
        for definition in definitions:
            identity = (definition["product_ident"], definition["digest"])
            if identity not in known_versions:
                inventory.entries.append(_row(
                    resource="specifications", title=definition["product_ident"],
                    product_ident=definition["product_ident"], version_id=definition["digest"], digest=definition["digest"],
                    source="Catalog history retained", source_kind="catalog", area="uploaded-specifications", path="", kind="file",
                    status="unavailable", available=False, catalog_only=True,
                    message="Original file not located. Catalog history is retained; this record does not establish the current runtime version.",
                ))
                known_versions.add(identity)
        for row in inventory.entries:
            row["product_name"] = products.get(row["product_ident"], "")
            definition = definition_map.get((row["product_ident"], row.get("digest")))
            if not definition:
                continue
            row["description"] = definition["description"]
            row["imported_at"] = definition["imported_at"].isoformat()
            definition_links = release_map.get(definition["pk"], ())
            row["catalog_is_current"] = any(link["product_release__is_current"] for link in definition_links)
            row["catalog_status_label"] = "Current catalog revision" if row["catalog_is_current"] else "Catalog history"
            row["revision_labels"] = tuple(dict.fromkeys(
                "Revision " + str(link["product_release__revision"])
                for link in definition_links
            ))
            if row["revision_labels"]:
                row["version_label"] = ", ".join(row["revision_labels"])
    except DatabaseError:
        inventory.warn("Catalog descriptions and revision dates are temporarily unavailable. Original files can still be browsed and downloaded.")


def list_versions(kind, *, page=1, page_size=50, query="", status="all", include_catalog=True, include_sources=True):
    """Return a bounded, searchable page without changing any active version.

    ``include_catalog=False`` keeps this reader independent of SQL during a
    database maintenance window. File availability never depends on optional
    catalog enrichment, and no specification payload is parsed or hashed.
    ``include_sources=False`` hides unversioned historical source records while
    retaining a currently selected installed source and missing-version markers.
    """
    if not isinstance(kind, str) or kind not in {"boundaries", "specifications"}:
        raise files.StorageError("Choose boundary or specification versions.", code="invalid_version_kind", status_code=404)
    inventory = _Inventory()
    (_boundaries if kind == "boundaries" else _specifications)(inventory)
    if kind == "specifications":
        _merge_specification_locations(inventory)
        if include_catalog:
            _catalog_metadata(inventory)
    query = str(query or "")[:150].casefold()
    status = status if status in _STATUS_LABELS else "all"
    entries = [row for row in inventory.entries if
               (include_sources or row["versioned"] or row["status"] == "current") and
               (status == "all" or row["status"] == status) and
               (not query or query in " ".join(str(row[key]) for key in ("title", "product_name", "product_ident", "version_id", "source", "description")).casefold())]
    entries.sort(key=lambda row: (row["modified_at"] or row["imported_at"] or "", row["version_id"]), reverse=True)
    entries.sort(key=lambda row: row["status"] != "current")
    entries.sort(key=lambda row: row["product_ident"])
    page_size = min(max(page_size if type(page_size) is int else 50, 1), 100)
    try:
        page = max(int(page), 1)
    except (ValueError, TypeError):
        page = 1
    total = len(entries)
    version_count = sum(row["versioned"] for row in entries)
    source_count = total - version_count
    page = min(page, max((total + page_size - 1) // page_size, 1))
    entries = entries[(page - 1) * page_size:page * page_size]
    if inventory.scan_limited:
        inventory.warn("The version inventory reached its scan limit. Some versions may be omitted; refine the configured source or inspect a specific folder.")
    return {
        "kind": kind, "entries": entries, "total": total, "page": page,
        "page_size": page_size, "has_previous": page > 1, "has_next": page * page_size < total,
        "query": query, "status": status, "include_sources": bool(include_sources),
        "version_count": version_count, "source_count": source_count,
        "scan_limited": inventory.scan_limited,
        "scanned_count": inventory.scanned_count, "skipped_count": inventory.skipped_count,
        "warnings": inventory.warnings,
    }
