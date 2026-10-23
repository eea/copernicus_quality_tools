"""Versioned expected-artifact links, independent of optional transported bytes.

Expected historical evidence is never replaced by a newly observed checksum.
The ledger is bounded receipt data, not an executable source operation or a path
outside the application's already constrained business namespaces.
"""

from copy import deepcopy
import hashlib
import os
from pathlib import Path
import re
from uuid import NAMESPACE_URL, UUID, uuid5

from qc_tool.common import JOB_INPUT_DIRNAME, JOB_OUTPUT_DIRNAME

from .archive import ArtifactSource, TransferArchiveError, _hash, _json, canonical_json, open_regular, validate_key


VERSION = 1
MAX_REFERENCES = 100_000
MAX_RECEIPTS = 10_000
MAX_STORED_REFERENCES = 1_000_000
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = {"id", "origin", "resource", "source_key", "role", "root", "key", "kind",
           "expected_sha256", "expected_size", "observed_sha256", "observed_size",
           "availability", "inclusion"}
_AVAILABILITY = {"verified", "unverified", "missing", "different", "remote", "unknown"}
_INCLUSION = {"included", "excluded", "unavailable", "external"}


def _rows(payload, resource):
    return payload.get("records", {}).get(resource, [])


def _index(payload):
    return {resource: {str(row[{"jobs": "job_uuid", "submissions": "submission_uuid"}.get(resource, "id")]): row
                       for row in rows} for resource, rows in payload.get("records", {}).items()}


def _legacy_namespace(payload):
    return str(uuid5(NAMESPACE_URL, "qc-tool-artifact-legacy:" + hashlib.sha256(canonical_json({
        "contract": payload.get("contract"), "accounts": payload.get("accounts", []),
        "records": payload.get("records", {}),
    })).hexdigest()))


def _origin(payload, resource, key):
    value = (payload.get("provenance") or {}).get("identities", {}).get(resource, {}).get(str(key))
    if value:
        return deepcopy(value)
    namespace = payload.get("_reference_namespace") or _legacy_namespace(payload)
    return {"namespace": namespace, "key": str(key)}


def _identifier(origin, resource, role, root, key):
    return str(uuid5(NAMESPACE_URL, canonical_json([origin, resource, role, root, key]).decode()))


def _reference(payload, resource, row_key, role, root, key, *, kind="file", sha256=None, size=None):
    origin = _origin(payload, resource, row_key)
    return {"id": _identifier(origin, resource, role, root, key), "origin": origin,
            "resource": resource, "source_key": str(row_key), "role": role, "root": root, "key": key,
            "kind": kind, "expected_sha256": sha256 or None, "expected_size": size,
            "observed_sha256": None, "observed_size": None,
            "availability": "unknown", "inclusion": "unavailable"}


def _safe_file(root, key, *, checksum=True, max_bytes=16 * 1024**3):
    from .artifacts import _safe_directory
    parent = str(Path(key).parent)
    if _safe_directory(root, "" if parent == "." else parent, required=False) is None:
        return None
    path = Path(root) / key
    if path.is_symlink():
        raise TransferArchiveError("Artifact storage contains a symbolic link.")
    if not path.exists():
        return None
    # open_regular rejects nonregular files and unsafe descriptor ancestry.
    with open_regular(path, storage_root=root) as stream:
        size = os.fstat(stream.fileno()).st_size
        if checksum and size > max_bytes:
            raise TransferArchiveError("An artifact exceeds its supported size limit.")
        digest = None
        if checksum:
            digest, size = _hash(stream, max_bytes)
    return ArtifactSource("", key, path, Path(root)), digest, size


def collect_optional_artifacts(payload, *, roots, include_files):
    """Observe known business namespaces; missing bytes retain expected links."""
    from .artifacts import ArtifactInventory, _safe_directory, _tree, _verify_receipt
    from qc_tool.frontend.dashboard.services.boundaries.resolver import resolve_boundary_generation
    from qc_tool.frontend.dashboard.services.boundaries.errors import BoundaryGenerationUnavailable
    from qc_tool.frontend.dashboard.services.submissions.publication.integrity import _expected_inventory

    if payload.get("profile") == "accounts":
        return ArtifactInventory()
    roots = {name: Path(value) for name, value in roots.items()}
    context = {**payload, "_reference_namespace": _legacy_namespace(payload)}
    sources, directories, items, warnings, external = {}, {}, [], [], []
    accounts = {int(row["key"]): row["username"] for row in payload.get("accounts", [])}
    deliveries = {str(row["id"]): row for row in _rows(payload, "deliveries")}

    def observe(ref, *, candidate=None):
        if len(items) >= MAX_REFERENCES:
            raise TransferArchiveError("The artifact reference inventory exceeds its supported bound.")
        items.append(ref)
        if not ref["root"] or not ref["key"] or ref["root"] not in roots:
            ref.update(availability="remote" if ref["root"] == "" else "missing",
                       inclusion="external" if ref["root"] == "" else "unavailable")
            return ref
        if ref["kind"] == "tree":
            present = _safe_directory(roots[ref["root"]], ref["key"], required=False) is not None
            ref.update(availability="unverified" if present else "missing",
                       inclusion="excluded" if present else "unavailable")
            return ref
        result = candidate or _safe_file(roots[ref["root"]], ref["key"], checksum=include_files)
        if result is None:
            ref.update(availability="missing", inclusion="unavailable")
            warnings.append(f"{ref['resource']} {ref['source_key']}: {ref['role']} is unavailable; its reference is retained.")
            return ref
        source, digest, size = result
        ref.update(observed_sha256=digest, observed_size=size)
        different = ((digest is not None and ref["expected_sha256"] is not None and ref["expected_sha256"] != digest)
                     or (ref["expected_size"] is not None and ref["expected_size"] != size))
        if different:
            ref.update(availability="different", inclusion="unavailable")
            warnings.append(f"{ref['resource']} {ref['source_key']}: retained {ref['role']} differs from expected evidence; bytes were excluded.")
        else:
            ref.update(availability="verified" if digest is not None and ref["expected_sha256"] else "unverified",
                       inclusion="included" if include_files else "excluded")
            if include_files:
                sources[(ref["root"], ref["key"])] = ArtifactSource(ref["root"], ref["key"], source.path, source.storage_root)
        return ref

    def input_reference(resource, key, role, delivery, digest):
        owner = accounts.get(delivery.get("user_id"))
        local = delivery.get("s3_id") is None and owner is not None
        name = delivery["filename"]
        if Path(name).name != name or not name.lower().endswith(".zip"):
            raise TransferArchiveError("A retained delivery uses an unsupported upload filename.")
        path = validate_key(owner + "/" + name) if local else ""
        ref = _reference(context, resource, key, role, "incoming" if local else "", path,
                         sha256=digest, size=delivery["size_bytes"])
        if not owner and delivery.get("s3_id") is None:
            ref.update(availability="missing", inclusion="unavailable")
            items.append(ref)
            warnings.append(f"Delivery {delivery['id']} has no retained storage owner; its input reference is preserved.")
            return
        observe(ref)

    for row in deliveries.values():
        input_reference("deliveries", row["id"], "delivery_input", row, row.get("content_sha256"))
        if row.get("s3_id") is not None:
            external.append(f"Remote delivery {row['id']} requires separately provisioned access; remote objects and credentials are excluded.")
    for row in _rows(payload, "jobs"):
        key = str(row["job_uuid"])
        delivery = deliveries.get(str(row.get("delivery_id")))
        if delivery is not None:
            input_reference("jobs", key, "job_input", delivery, row.get("input_sha256"))
        prefix = "job_" + UUID(key).hex
        observe(_reference(context, "jobs", key, "job_artifacts", "work", prefix, kind="tree"))
        if "work" not in roots or _safe_directory(roots["work"], prefix, required=False) is None:
            continue
        found, found_dirs = [], []
        for entry in sorted(os.scandir(roots["work"] / prefix), key=lambda value: value.name):
            relative = prefix + "/" + entry.name
            if entry.name == JOB_OUTPUT_DIRNAME:
                _tree(roots["work"], relative, found, found_dirs, root_name="work")
            elif entry.is_symlink():
                raise TransferArchiveError("A retained job artifact is a symbolic link.")
            elif entry.is_file(follow_symlinks=False) and not entry.name.lower().endswith((".log", ".stdout", ".pre")):
                found.append(ArtifactSource("work", relative, Path(entry.path), roots["work"]))
            elif not entry.is_dir(follow_symlinks=False) and not entry.is_file(follow_symlinks=False):
                raise TransferArchiveError("A retained job artifact is a special file.")
        for source in found:
            observe(_reference(context, "jobs", key, "job_output", "work", source.key))
        if include_files:
            directories[("work", prefix)] = {"root": "work", "key": prefix}
            directories.update({(item["root"], item["key"]): item for item in found_dirs})
    for row in _rows(payload, "submissions"):
        if row["publication_state"] != "published":
            continue
        key, prefix = str(row["submission_uuid"]), validate_key(row["artifact_key"])
        observe(_reference(context, "submissions", key, "publication", "submissions", prefix, kind="tree"))
        manifest_ref = observe(_reference(context, "submissions", key, "publication_manifest", "submissions", prefix + "/submission-manifest.json"))
        if manifest_ref["observed_size"] is None:
            continue
        with open_regular(roots["submissions"] / manifest_ref["key"], storage_root=roots["submissions"]) as stream:
            original = stream.read(2 * 1024**2 + 1)
        if len(original) > 2 * 1024**2:
            raise TransferArchiveError("A publication manifest exceeds its size limit.")
        manifest_ref.update(observed_sha256=hashlib.sha256(original).hexdigest(), observed_size=len(original))
        manifest = _json(original)
        _verify_receipt(manifest, row, payload)
        try:
            expected = _expected_inventory(manifest, "submission-manifest.json")
        except ValueError as error:
            raise TransferArchiveError("A publication inventory is invalid.") from error
        inputs = [value for name, value in expected.items() if name.startswith(JOB_INPUT_DIRNAME + "/")]
        if len(inputs) != 1 or inputs[0][0] != row["input_digest"] or "SUBMITTED" not in expected:
            raise TransferArchiveError("A publication inventory has no verified original input.")
        for relative, (digest, size) in expected.items():
            observe(_reference(context, "submissions", key, "publication_file", "submissions",
                               prefix + "/" + validate_key(relative), sha256=digest, size=size))
    for row in _rows(payload, "definitions"):
        key = "product_definitions/.versions/" + row["product_ident"] + "/" + row["digest"] + ".json"
        ref = _reference(context, "definitions", row["id"], "specification", "work", key, sha256=row["digest"])
        candidates = [("work", key), ("work", "product_definitions/" + row["product_ident"] + ".json")]
        candidates += [(name, row["product_ident"] + ".json") for name in roots if name.startswith("product-")]
        candidate = None
        for name, path in candidates:
            if name not in roots:
                continue
            inspected = _safe_file(roots[name], path, max_bytes=1024**2)
            if inspected is not None and inspected[1] == row["digest"]:
                candidate = inspected
                break
        observe(ref, candidate=candidate)
    boundary = {}
    boundary_reference = _reference(context, "configuration", "boundaries", "boundary_inventory", "boundaries", "", kind="tree")
    items.append(boundary_reference)
    if "boundaries" in roots and _safe_directory(roots["boundaries"], required=False) is not None and any(roots["boundaries"].iterdir()):
        boundary_reference.update(availability="unverified", inclusion="excluded")
        try:
            generation = resolve_boundary_generation(roots["boundaries"])
        except BoundaryGenerationUnavailable:
            generation = None
            boundary_reference.update(availability="missing", inclusion="unavailable")
            warnings.append("No active boundary generation is available; safe retained generations are inventoried without activation.")
            for name in ("raster", "vector"):
                path = roots["boundaries"] / name
                if path.is_symlink() and os.readlink(path) != ".boundary-current/" + name:
                    raise TransferArchiveError("Boundary compatibility storage contains an unsafe link.")
        except Exception as error:
            raise TransferArchiveError("The active boundary generation cannot be resolved safely.") from error
        prefixes = []
        if generation is None or generation.managed:
            from qc_tool.frontend.dashboard.services.boundaries.layout import validate_generation_id
            parent = _safe_directory(roots["boundaries"], ".boundary-generations", required=False)
            if parent is not None:
                for entry in sorted(os.scandir(parent), key=lambda value: value.name):
                    validate_generation_id(entry.name)
                    prefixes.append(".boundary-generations/" + entry.name)
            if include_files:
                boundary = ({"mode": "retained"} if generation is None else
                            {"mode": "managed", "generation": generation.generation_id})
        else:
            prefixes = ["raster", "vector"]
            if include_files:
                boundary = {"mode": "legacy"}
        for prefix in prefixes:
            found, found_dirs = [], []
            _tree(roots["boundaries"], prefix, found, found_dirs, root_name="boundaries")
            for source in found:
                observe(_reference(context, "configuration", "boundaries", "boundary_file", "boundaries", source.key))
            if include_files:
                directories.update({(item["root"], item["key"]): item for item in found_dirs})
    else:
        boundary_reference.update(availability="missing", inclusion="unavailable")
        warnings.append("Boundary storage is empty or unavailable; no historical job boundary generation is inferred.")
    # New files always carry all existing parents in the bounded destination tree.
    for root, key in sources:
        for length in range(1, len(Path(key).parts)):
            parent = "/".join(Path(key).parts[:length])
            directories[(root, parent)] = {"root": root, "key": parent}
    from types import SimpleNamespace
    from .artifacts import _allowed_paths
    allowed = _allowed_paths(SimpleNamespace(records=payload, storage={"boundaries": boundary}))
    directories = {key: value for key, value in directories.items() if allowed(key[0], key[1], True)}
    refs = {"version": VERSION, "mode": "available_files" if include_files else "records_only", "items": items}
    refs = merge_retained_references(refs, payload, retained_references(payload))
    included_locations = {(item["root"], item["key"]) for item in refs["items"] if item["inclusion"] == "included"}
    sources = {key: source for key, source in sources.items() if key in included_locations}
    return ArtifactInventory(tuple(sources[key] for key in sorted(sources)),
                             tuple(directories[key] for key in sorted(directories)),
                             {"boundaries": boundary, "references": refs}, tuple(warnings), tuple(external))


def _validate_items(value, payload, *, entries=None):
    if (not isinstance(value, dict) or set(value) != {"version", "mode", "items"}
            or type(value["version"]) is not int or value["version"] != VERSION
            or not isinstance(value["mode"], str) or value["mode"] not in {"records_only", "available_files"}
            or not isinstance(value["items"], list) or len(value["items"]) > MAX_REFERENCES):
        raise TransferArchiveError("The artifact reference contract is invalid or unsupported.")
    index, identifiers, identities = _index(payload), set(), set()
    from .artifacts import _allowed_paths
    from types import SimpleNamespace
    allowed = _allowed_paths(SimpleNamespace(records=payload, storage={"boundaries": {}}))
    accounts = {int(account["key"]): account["username"] for account in payload.get("accounts", [])}
    # Boundary references describe configured historical storage, not activation.
    for item in value["items"]:
        if not isinstance(item, dict) or set(item) != _FIELDS:
            raise TransferArchiveError("An artifact reference has an invalid field contract.")
        if any(not isinstance(item[field], str) for field in ("id", "resource", "source_key", "role", "root", "key", "kind", "availability", "inclusion")):
            raise TransferArchiveError("An artifact reference contains an invalid typed value.")
        try:
            if str(UUID(item["id"])) != item["id"] or str(UUID(item["origin"]["namespace"])) != item["origin"]["namespace"]:
                raise ValueError
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            raise TransferArchiveError("An artifact reference identity is invalid.") from error
        if (not isinstance(item["origin"], dict) or set(item["origin"]) != {"namespace", "key"}
                or not isinstance(item["origin"]["key"], str) or not item["origin"]["key"]
                or not isinstance(item["source_key"], str) or not isinstance(item["role"], str)
                or item["kind"] not in {"file", "tree"} or item["availability"] not in _AVAILABILITY
                or item["inclusion"] not in _INCLUSION):
            raise TransferArchiveError("An artifact reference state or origin is invalid.")
        if item["id"] != _identifier(item["origin"], item["resource"], item["role"], item["root"], item["key"]):
            raise TransferArchiveError("An artifact reference identity differs from its origin and role.")
        for field in ("expected_sha256", "observed_sha256"):
            if item[field] is not None and (not isinstance(item[field], str) or not _SHA.fullmatch(item[field])):
                raise TransferArchiveError("An artifact reference checksum is invalid.")
        for field in ("expected_size", "observed_size"):
            if item[field] is not None and (type(item[field]) is not int or not 0 <= item[field] <= 2**63 - 1):
                raise TransferArchiveError("An artifact reference size is invalid.")
        if ((item["observed_sha256"] is not None and item["observed_size"] is None)
                or (item["availability"] == "verified" and
                    (item["expected_sha256"] is None or item["observed_sha256"] != item["expected_sha256"]
                     or (item["expected_size"] is not None and item["observed_size"] != item["expected_size"])))):
            raise TransferArchiveError("An artifact reference verification claim has no matching evidence.")
        if item["id"] in identifiers:
            raise TransferArchiveError("The artifact reference inventory repeats an identity.")
        identifiers.add(item["id"])
        identity = (item["resource"], item["source_key"], item["role"], item["root"], item["key"])
        if identity in identities:
            raise TransferArchiveError("The artifact reference inventory repeats a domain link.")
        identities.add(identity)
        resource, key, role = item["resource"], item["source_key"], item["role"]
        row = index.get(resource, {}).get(key)
        if resource == "configuration":
            if key != "boundaries" or role not in {"boundary_file", "boundary_inventory"} or item["root"] != "boundaries":
                raise TransferArchiveError("An artifact reference has an unsupported configuration link.")
            if role == "boundary_inventory":
                if item["key"] or item["kind"] != "tree":
                    raise TransferArchiveError("A boundary inventory descriptor cannot provide an arbitrary location.")
            else:
                validate_key(item["key"])
            if role == "boundary_file" and not (item["key"].startswith(("raster/", "vector/", ".boundary-generations/"))):
                raise TransferArchiveError("A boundary reference has an unsupported namespace.")
        else:
            if row is None:
                raise TransferArchiveError("An artifact reference is outside the included record graph.")
            allowed_roles = {"deliveries": {"delivery_input"}, "jobs": {"job_input", "job_artifacts", "job_output"},
                             "submissions": {"publication", "publication_manifest", "publication_file"},
                             "definitions": {"specification"}}
            if role not in allowed_roles.get(resource, set()):
                raise TransferArchiveError("An artifact reference has an unsupported domain role.")
            if role in {"delivery_input", "job_input"}:
                delivery = row if resource == "deliveries" else index.get("deliveries", {}).get(str(row.get("delivery_id")))
                if delivery is None:
                    raise TransferArchiveError("A job input reference has no included delivery.")
                owner = accounts.get(delivery.get("user_id"))
                local = owner is not None and delivery.get("s3_id") is None
                expected_location = ("incoming", owner + "/" + delivery["filename"]) if local else ("", "")
                if (item["root"], item["key"]) != expected_location or item["kind"] != "file" or item["expected_size"] != delivery["size_bytes"]:
                    raise TransferArchiveError("An input reference changes its delivery or storage ownership.")
            elif role in {"job_artifacts", "job_output"}:
                prefix = "job_" + UUID(row["job_uuid"]).hex
                if (item["root"] != "work" or (item["key"] != prefix if role == "job_artifacts" else not item["key"].startswith(prefix + "/"))
                        or item["kind"] != ("tree" if role == "job_artifacts" else "file")):
                    raise TransferArchiveError("A job artifact reference changes its owning job.")
            elif role.startswith("publication"):
                prefix = row.get("artifact_key", "")
                expected = prefix if role == "publication" else prefix + "/submission-manifest.json" if role == "publication_manifest" else None
                if (row.get("publication_state") != "published" or item["root"] != "submissions"
                        or (item["key"] != expected if expected is not None else not item["key"].startswith(prefix + "/"))
                        or item["kind"] != ("tree" if role == "publication" else "file")):
                    raise TransferArchiveError("A publication artifact reference changes its immutable owner.")
            elif role == "specification":
                expected = "product_definitions/.versions/" + row["product_ident"] + "/" + row["digest"] + ".json"
                if (item["root"], item["key"], item["kind"]) != ("work", expected, "file"):
                    raise TransferArchiveError("A specification reference changes its immutable version.")
            if item["root"]:
                validate_key(item["key"])
                # job_input refers to its delivery's canonical incoming location.
                if not allowed(item["root"], item["key"], item["kind"] == "tree"):
                    raise TransferArchiveError("An artifact reference is outside a supported business namespace.")
            elif item["key"]:
                raise TransferArchiveError("An unresolved artifact reference cannot contain a path.")
            expected_digest = (row.get("content_sha256") if role == "delivery_input" else
                               row.get("input_sha256") if role == "job_input" else
                               row.get("digest") if role == "specification" else None)
            if role in {"delivery_input", "job_input", "specification"} and item["expected_sha256"] != (expected_digest or None):
                raise TransferArchiveError("An artifact reference changes its recorded historical checksum.")
            if role == "delivery_input" and item["expected_size"] != row["size_bytes"]:
                raise TransferArchiveError("An artifact reference changes the delivery's recorded size.")
        if item["inclusion"] == "included":
            entry = (entries or {}).get((item["root"], item["key"]))
            if (value["mode"] != "available_files" or item["kind"] != "file" or entry is None
                    or item["availability"] not in {"verified", "unverified"}
                    or (item["observed_sha256"], item["observed_size"]) != (entry["sha256"], entry["size"])
                    or (item["expected_sha256"] is not None and item["expected_sha256"] != entry["sha256"])
                    or (item["expected_size"] is not None and item["expected_size"] != entry["size"])):
                raise TransferArchiveError("An included artifact does not match its expected and observed evidence.")
    return identities


def validate_reference_inventory(archive):
    """Validate every declared link and account for every actual payload."""
    entries = {(item["root"], item["key"]): item for item in archive.entries}
    refs = archive.storage.get("references")
    identities = _validate_items(refs, archive.records, entries=entries)
    included = {(item["root"], item["key"]) for item in refs["items"] if item["inclusion"] == "included"}
    if included != set(entries) or (refs["mode"] == "records_only" and archive.directories):
        raise TransferArchiveError("The artifact payload inventory differs from its declared references.")
    domain_roles = {identity[:3] for identity in identities}
    index = _index(archive.records)
    for resource, role in (("deliveries", "delivery_input"), ("jobs", "job_artifacts"), ("jobs", "job_input"),
                           ("definitions", "specification")):
        for key in index.get(resource, {}):
            if (resource, key, role) not in domain_roles:
                raise TransferArchiveError("A record is missing its required expected-artifact reference.")
    for key, row in index.get("submissions", {}).items():
        if row["publication_state"] == "published" and ("submissions", key, "publication_manifest") not in domain_roles:
            raise TransferArchiveError("A published record is missing its manifest reference.")
    return refs


def filter_references(value, included):
    result = deepcopy(value)
    result["items"] = [item for item in result["items"] if item["resource"] != "configuration"
                       and item["source_key"] in {str(key) for key in included.get(item["resource"], ())}]
    return result


def without_payloads(archive):
    """Use the validated original package as evidence, without restoring bytes."""
    from dataclasses import replace
    from .artifacts import _validate_package_artifacts
    _validate_package_artifacts(archive)
    if archive.records.get("profile") != "application":
        return archive
    if "references" in archive.storage:
        refs = deepcopy(archive.storage["references"])
        refs["mode"] = "records_only"
        for item in refs["items"]:
            if item["inclusion"] == "included":
                item["inclusion"] = "excluded"
    else:
        # Legacy bytes remain validated before conversion; collect through a
        # private source map, never through filesystem or destination guessing.
        refs = references_from_archive(archive)
    storage = {**archive.storage, "boundaries": {}, "references": refs}
    result = replace(archive, entries=(), directories=(), storage=storage)
    validate_reference_inventory(result)
    return result


def references_from_archive(archive):
    """Describe legacy payload evidence without rewriting original documents."""
    items, accounts = [], {int(row["key"]): row["username"] for row in archive.records.get("accounts", [])}
    context = {**archive.records, "_reference_namespace": _legacy_namespace(archive.records)}
    entries = {(item["root"], item["key"]): item for item in archive.entries}
    def add(ref):
        entry = entries.get((ref["root"], ref["key"]))
        if entry:
            ref.update(observed_sha256=entry["sha256"], observed_size=entry["size"],
                       availability="verified" if ref["expected_sha256"] else "unverified", inclusion="excluded")
        else:
            ref.update(availability="missing", inclusion="unavailable")
        items.append(ref)
    for row in _rows(archive.records, "deliveries"):
        owner = accounts.get(row["user_id"])
        local = owner is not None and row["s3_id"] is None
        add(_reference(context, "deliveries", row["id"], "delivery_input", "incoming" if local else "",
                       owner + "/" + row["filename"] if local else "", sha256=row.get("content_sha256"), size=row["size_bytes"]))
    for row in _rows(archive.records, "jobs"):
        prefix = "job_" + UUID(row["job_uuid"]).hex
        add(_reference(context, "jobs", row["job_uuid"], "job_artifacts", "work", prefix, kind="tree"))
        delivery = next((delivery for delivery in _rows(archive.records, "deliveries") if delivery["id"] == row.get("delivery_id")), None)
        if delivery is not None:
            owner = accounts.get(delivery["user_id"])
            local = owner is not None and delivery["s3_id"] is None
            add(_reference(context, "jobs", row["job_uuid"], "job_input", "incoming" if local else "",
                           owner + "/" + delivery["filename"] if local else "", sha256=row.get("input_sha256"), size=delivery["size_bytes"]))
        for (root, key), entry in entries.items():
            if root == "work" and key.startswith(prefix + "/"):
                add(_reference(context, "jobs", row["job_uuid"], "job_output", root, key))
    for row in _rows(archive.records, "submissions"):
        if row["publication_state"] != "published":
            continue
        prefix = row["artifact_key"]
        add(_reference(context, "submissions", row["submission_uuid"], "publication_manifest", "submissions", prefix + "/submission-manifest.json"))
        for (root, key), entry in entries.items():
            if root == "submissions" and key.startswith(prefix + "/") and not key.endswith("/submission-manifest.json"):
                add(_reference(context, "submissions", row["submission_uuid"], "publication_file", root, key,
                               sha256=entry["sha256"], size=entry["size"]))
    for row in _rows(archive.records, "definitions"):
        key = "product_definitions/.versions/" + row["product_ident"] + "/" + row["digest"] + ".json"
        ref = _reference(context, "definitions", row["id"], "specification", "work", key, sha256=row["digest"])
        matching = next((entry for entry in archive.entries if entry["sha256"] == row["digest"]), None)
        if matching:
            ref.update(observed_sha256=matching["sha256"], observed_size=matching["size"], availability="verified", inclusion="excluded")
            items.append(ref)
        else:
            add(ref)
    return {"version": VERSION, "mode": "records_only", "items": items}


def receipt_references(archive, result):
    """Bind immutable source links to the locally committed identity mapping."""
    if "references" not in archive.storage:
        return None
    refs = deepcopy(validate_reference_inventory(archive))
    mappings = result.get("identity_map", {})
    for item in refs["items"]:
        if item["resource"] == "configuration":
            continue
        target = mappings.get(item["resource"], {}).get(item["source_key"])
        if target is None:
            raise TransferArchiveError("An imported artifact reference has no committed destination identity.")
        item["source_key"] = str(target)
    if "contract" in archive.records:
        from qc_tool.database.models import TransferReceipt
        proposed = {item["id"]: item for item in refs["items"]}
        receipts = TransferReceipt.objects.filter(summary__has_key="artifact_references").order_by("pk")
        if receipts.count() > MAX_RECEIPTS:
            raise TransferArchiveError("The retained artifact ledger exceeds its supported receipt bound.")
        scanned = 0
        for receipt in receipts.iterator(chunk_size=100):
            retained = receipt.summary.get("artifact_references")
            if retained is None:
                continue
            if not isinstance(retained, dict) or retained.get("version") != VERSION or not isinstance(retained.get("items"), list):
                raise TransferArchiveError("The retained artifact ledger contains unsupported identity evidence.")
            scanned += len(retained["items"])
            if scanned > MAX_STORED_REFERENCES:
                raise TransferArchiveError("The retained artifact ledger exceeds its supported reference bound.")
            for previous in retained["items"]:
                if not isinstance(previous, dict) or not isinstance(previous.get("id"), str):
                    raise TransferArchiveError("The retained artifact ledger contains malformed identity evidence.")
                current = proposed.get(previous["id"])
                if current is None:
                    continue
                binding = ("origin", "resource", "source_key", "role", "root", "key", "kind")
                if any(previous.get(field) != current[field] for field in binding):
                    raise TransferArchiveError("An artifact identity is already bound to another committed record.")
                if previous.get("expected_sha256") is not None and previous["expected_sha256"] != current["expected_sha256"]:
                    raise TransferArchiveError("An artifact identity conflicts with its committed expected bytes.")
    # Stored data is an observation/expected link, never a claim that old payloads
    # remain included in a later package.
    refs["mode"] = "records_only"
    for item in refs["items"]:
        if item["inclusion"] == "included":
            item["inclusion"] = "excluded"
    return refs


def retained_references(payload):
    """Read bounded committed reference data, projected onto this exact graph."""
    from django.db import connection
    from qc_tool.database.models import TransferReceipt
    # Pure archive tests intentionally have no database; only actual ORM exports
    # carry a typed contract and can have committed local receipts.
    if "contract" not in payload or not connection.settings_dict.get("NAME"):
        return []
    index, found = _index(payload), {}
    receipts = TransferReceipt.objects.filter(summary__has_key="artifact_references").order_by("pk")
    if receipts.count() > MAX_RECEIPTS:
        raise TransferArchiveError("The retained artifact ledger exceeds its supported receipt bound.")
    for receipt in receipts.iterator(chunk_size=100):
        refs = receipt.summary["artifact_references"]
        if refs is None:
            continue
        if (not isinstance(refs, dict) or set(refs) != {"version", "mode", "items"}
                or type(refs.get("version")) is not int or refs["version"] != VERSION
                or not isinstance(refs.get("items"), list) or len(refs["items"]) > MAX_REFERENCES
                or any(not isinstance(item, dict) or set(item) != _FIELDS
                       or not isinstance(item.get("resource"), str) or not isinstance(item.get("source_key"), str) for item in refs["items"])):
            raise TransferArchiveError("The retained artifact ledger contains an unsupported contract.")
        selected = {"version": VERSION, "mode": "records_only", "items": [deepcopy(item) for item in refs["items"]
                    if isinstance(item, dict) and item.get("source_key") in index.get(item.get("resource"), {})]}
        _validate_items(selected, payload)
        for item in selected["items"]:
            previous = found.get(item["id"])
            if previous and any(previous[field] != item[field] for field in ("origin", "resource", "source_key", "role", "root", "key", "expected_sha256", "expected_size")):
                raise TransferArchiveError("The retained artifact ledger has contradictory expected identities.")
            found[item["id"]] = item
            if len(found) > MAX_REFERENCES:
                raise TransferArchiveError("The retained artifact ledger exceeds its supported reference bound.")
    return list(found.values())


def merge_retained_references(value, payload, retained):
    """Retain known missing historical inventory across a later export."""
    current = {(item["resource"], item["source_key"], item["role"], item["root"], item["key"]): item for item in value["items"]}
    for old in retained:
        key = (old["resource"], old["source_key"], old["role"], old["root"], old["key"])
        new = current.get(key)
        if new is not None:
            if old["expected_sha256"] and new["expected_sha256"] and old["expected_sha256"] != new["expected_sha256"]:
                raise TransferArchiveError("Retained artifact evidence contradicts the current expected bytes.")
            new["id"], new["origin"] = old["id"], deepcopy(old["origin"])
            if new["role"] not in {"delivery_input", "job_input", "specification"}:
                # A previous exported output/manifest observation identifies
                # that artifact version. This does not fill a missing past-job
                # input checksum or invent an association to a raw ZIP.
                known = old["expected_sha256"] or old["observed_sha256"]
                known_size = old["expected_size"] if old["expected_size"] is not None else old["observed_size"]
                if known is not None:
                    new["expected_sha256"], new["expected_size"] = known, known_size
                    if new["observed_sha256"] is not None and (new["observed_sha256"], new["observed_size"]) != (known, known_size):
                        new.update(availability="different", inclusion="unavailable")
            if new["expected_sha256"] is None:
                new["expected_sha256"] = old["expected_sha256"]
            if new["expected_size"] is None:
                new["expected_size"] = old["expected_size"]
            if new["observed_sha256"] is None:
                new["observed_sha256"] = old["observed_sha256"]
                new["observed_size"] = old["observed_size"]
        else:
            new = deepcopy(old)
            new.update(availability="missing", inclusion="unavailable")
            current[key] = new
    if len(current) > MAX_REFERENCES:
        raise TransferArchiveError("The retained artifact inventory exceeds its supported bound.")
    return {**value, "items": list(current.values())}


def inspect_optional_delivery_files(archive, *, roots):
    """Missing or wrong existing bytes are visible history, not merge blockers."""
    refs = validate_reference_inventory(archive)
    lookup = {(item["resource"], item["source_key"], item["role"]): item for item in refs["items"]}
    jobs_by_delivery = {}
    for job in _rows(archive.records, "jobs"):
        jobs_by_delivery.setdefault(str(job.get("delivery_id")), []).append(job)
    accounts = {int(account["key"]): account["username"] for account in archive.records.get("accounts", [])}
    files = []
    for row in _rows(archive.records, "deliveries"):
        ref = lookup[("deliveries", str(row["id"]), "delivery_input")]
        related = jobs_by_delivery.get(str(row["id"]), [])
        packaged = ref["inclusion"] == "included"
        item = {"delivery_id": row["id"], "filename": row["filename"], "owner": "",
                "size": row["size_bytes"], "sha256": ref["expected_sha256"] or "", "job_count": len(related),
                "status": "missing", "file_status": "missing", "message": "Original ZIP is unavailable; its history and expected reference will be retained."}
        owner = accounts.get(row.get("user_id"), "")
        item["owner"] = owner
        if ref["root"] == "":
            item.update(status="remote" if row.get("s3_id") else "missing", file_status="remote" if row.get("s3_id") else "missing",
                        message="Remote or historical input requires separately established storage access.")
        elif packaged:
            item.update(status="packaged", file_status="packaged", message="Original ZIP is included; existing files will never be overwritten.")
        if ref["root"] in roots and ref["key"]:
            try:
                observed = _safe_file(Path(roots[ref["root"]]), ref["key"])
                if observed is not None:
                    _source, digest, size = observed
                    expected = ref["expected_sha256"] or ref["observed_sha256"]
                    if expected and digest == expected and size == row["size_bytes"]:
                        item.update(status="retained_verified", file_status="retained_verified", message="Matching retained ZIP can be reused; historical job checksums are verified separately.")
                    else:
                        item.update(status="different" if expected else "unverified_history", file_status="different" if expected else "unverified",
                                    message="Existing ZIP cannot establish this historical input. Records may be imported without linking or changing it.")
            except (OSError, ValueError):
                item.update(status="different", file_status="unavailable", message="Existing input storage cannot be verified safely. Its files will not be changed.")
        if related and any(not _SHA.fullmatch(job.get("input_sha256") or "") for job in related):
            item["message"] += " Some historical runs have no recorded input checksum."
        files.append(item)
    # Incoming payload collisions remain blockers, since applying them would
    # require replacing existing bytes. References-only mismatches are warnings.
    conflicts = []
    for item in files:
        ref = lookup[("deliveries", str(item["delivery_id"]), "delivery_input")]
        if ref["inclusion"] == "included" and item["status"] == "different":
            conflicts.append({"key": "deliveries:" + str(item["delivery_id"]), "resource": "deliveries",
                              "source_key": str(item["delivery_id"]), "reason": item["message"], "choices": ["skip"]})
    return {"files": files, "conflicts": conflicts}


def imported_delivery_requires_verification(delivery):
    """An imported unknown-hash input cannot use the legacy unchecked download."""
    from qc_tool.database.models import TransferReceipt
    receipts = TransferReceipt.objects.filter(summary__has_key="artifact_references").order_by("pk")
    if receipts.count() > MAX_RECEIPTS:
        return True
    for receipt in receipts.iterator(chunk_size=100):
        refs = receipt.summary.get("artifact_references")
        if refs is None:
            continue
        if not isinstance(refs, dict) or refs.get("version") != VERSION or not isinstance(refs.get("items"), list):
            return True
        if any(isinstance(item, dict) and item.get("resource") == "deliveries"
               and item.get("source_key") == str(delivery.pk) and item.get("role") == "delivery_input"
               for item in refs["items"]):
            return True
    return False
