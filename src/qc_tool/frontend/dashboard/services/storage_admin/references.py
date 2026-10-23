"""Read-only record associations and fail-closed storage usage checks.

Paths identify an existing application namespace; a matching filename or hash
elsewhere never creates ownership or a new association. Optional checksum
evidence must come from the filesystem service's open descriptor, not a form.
"""

from pathlib import PurePosixPath
import re
from urllib.parse import urlencode
from uuid import UUID

from django.db import DatabaseError
from django.db.models import Q
from django.urls import reverse

from qc_tool.common import JOB_INPUT_DIRNAME
from qc_tool.database.transfers.errors import TransferError
from qc_tool.frontend.dashboard.models import Delivery, DeliverySubmission, Job


MAX_REFERENCE_LINKS = 50
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_JOB_DIRECTORY = re.compile(r"job_([0-9a-f]{32})\Z")
_JOB_STDOUT = re.compile(r"job\.([0-9a-f-]{36})\.stdout\Z")
_IMMUTABLE_AREAS = frozenset({"published", "submissions", "boundaries", "specifications"})


class StorageReferenceError(ValueError):
    """A file cannot be changed safely through storage administration."""


def _path(value):
    if (not isinstance(value, str) or len(value) > 4096 or "\\" in value
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        raise StorageReferenceError("Choose a valid relative storage path.")
    path = PurePosixPath(value)
    if value and (path.is_absolute() or path.as_posix() != value or any(part in {".", ".."} for part in path.parts)):
        raise StorageReferenceError("Choose a valid relative storage path.")
    return path.parts if value else ()


def _evidence(value):
    if value is None:
        return None
    if (not isinstance(value, dict) or type(value.get("size")) is not int or value["size"] < 0
            or not isinstance(value.get("sha256"), str) or not _SHA256.fullmatch(value["sha256"])):
        raise StorageReferenceError("File checksum verification is unavailable. Inspect the file again.")
    return value


def _reference(kind, obj):
    labels = {"delivery": "Delivery", "job": "QC job", "submission": "Submission"}
    return {"kind": kind, "id": str(obj.pk), "label": f"{labels[kind]} {obj.pk}",
            "url": reverse("admin_database_record", args=[obj._meta.db_table, str(obj.pk)])}


def _base():
    return {"status": "unlinked", "label": "Unlinked", "checked": True, "protected": False,
            "can_quarantine": True, "message": "No database record references this storage path.",
            "references": [], "reference_count": 0, "truncated": False,
            "historical_status": "", "historical_message": "", "verified_jobs": [], "job_matches": []}


def _presentation(result):
    result["links"] = result["references"]
    result["status_label"] = result["label"]
    return result


def _protected(message):
    return {**_base(), "status": "protected", "label": "Protected", "protected": True,
            "can_quarantine": False, "message": message}


def _collect(result, kind, queryset):
    count = queryset.count()
    result["reference_count"] += count
    available = MAX_REFERENCE_LINKS - len(result["references"])
    if available > 0:
        result["references"].extend(
            _reference(kind, obj) for obj in queryset.order_by(queryset.model._meta.pk.name)[:available]
        )


def _historical(result, jobs, evidence):
    if not jobs.exists():
        return
    for job in jobs.select_related("delivery").order_by("job_uuid")[:MAX_REFERENCE_LINKS]:
        valid = isinstance(job.input_sha256, str) and _SHA256.fullmatch(job.input_sha256)
        verified = bool(valid and evidence is not None and evidence["sha256"] == job.input_sha256
                        and evidence["size"] == job.delivery.size_bytes)
        if not valid:
            message = "Historical unavailable: this QC job has no recorded input checksum."
        elif evidence is None:
            message = "Not verified. Check the ZIP against this job's recorded checksum and size."
        elif verified:
            message = "This ZIP matches this QC job's recorded SHA-256 and size."
        else:
            message = "Historical unavailable: the ZIP differs from this job's recorded checksum or size."
        result["job_matches"].append({**_reference("job", job), "verified": verified, "message": message})
    with_checksums = jobs.filter(input_sha256__regex=r"^[0-9a-f]{64}$")
    if not with_checksums.exists():
        result.update(historical_status="unavailable",
                      historical_message="Historical unavailable: these QC jobs have no recorded input checksum.")
        return
    if evidence is None:
        result.update(historical_status="unverified", historical_message=(
            "Historical input has not been verified. Check this ZIP against the linked jobs before relying on it."
        ))
        return
    matched = with_checksums.filter(input_sha256=evidence["sha256"], delivery__size_bytes=evidence["size"])
    count = matched.count()
    if not count:
        result.update(historical_status="unavailable", historical_message=(
            "Historical unavailable: this ZIP does not match a linked QC job's recorded checksum and size."
        ))
        return
    result.update(historical_status="verified", historical_message=(
        f"This ZIP matches {count} linked QC {'job' if count == 1 else 'jobs'} by SHA-256 and recorded size."
    ), verified_jobs=[_reference("job", job) for job in matched.order_by("job_uuid")[:MAX_REFERENCE_LINKS]])


def _incoming(result, parts, evidence, is_directory):
    if len(parts) not in {1, 2} or (len(parts) == 1 and not is_directory):
        raise StorageReferenceError("Incoming ZIPs must be directly inside their owner's folder.")
    deliveries = Delivery.objects.filter(user__username=parts[0], s3__isnull=True)
    if len(parts) == 2:
        deliveries = deliveries.filter(filename=parts[1])
    jobs = Job.objects.filter(delivery__in=deliveries)
    submissions = DeliverySubmission.objects.filter(delivery__in=deliveries)
    _collect(result, "delivery", deliveries)
    _collect(result, "job", jobs)
    _collect(result, "submission", submissions)
    if not is_directory and parts[-1].lower().endswith(".zip"):
        _historical(result, jobs, evidence)


def _job_id(parts):
    match = _JOB_DIRECTORY.fullmatch(parts[0])
    if match:
        return UUID(hex=match[1])
    match = _JOB_STDOUT.fullmatch(parts[0]) if len(parts) == 1 else None
    if match:
        try:
            identity = UUID(match[1])
        except ValueError:
            return None
        return identity if str(identity) == match[1] else None
    return None


def _jobs(result, parts, evidence, is_directory):
    identity = _job_id(parts)
    if identity is None:
        raise StorageReferenceError("Only recognized QC job storage can be managed here.")
    jobs = Job.objects.filter(pk=identity)
    _collect(result, "job", jobs)
    _collect(result, "delivery", Delivery.objects.filter(pk__in=jobs.values("delivery_id")))
    _collect(result, "submission", DeliverySubmission.objects.filter(job__in=jobs))
    if (not is_directory and len(parts) == 3 and parts[1] == JOB_INPUT_DIRNAME
            and parts[-1].lower().endswith(".zip")):
        _historical(result, jobs, evidence)


def _published(result, path, parts, evidence, is_directory):
    prefixes = ["/".join(parts[:index]) for index in range(1, len(parts) + 1)]
    condition = Q(artifact_key__in=prefixes)
    if is_directory:
        condition |= Q(artifact_key__startswith=path + "/")
    submissions = DeliverySubmission.objects.filter(condition).exclude(artifact_key="")
    _collect(result, "submission", submissions)
    _collect(result, "job", Job.objects.filter(pk__in=submissions.values("job_id")))
    if not is_directory and parts[-1].lower().endswith(".zip"):
        # A publication's input location is explicit, independent of today's
        # delivery filename. Hash equality proves bytes, not manifest validity.
        parent = "/".join(parts[:-2]) if len(parts) >= 3 and parts[-2] == JOB_INPUT_DIRNAME else ""
        inputs = submissions.filter(artifact_key=parent) if parent else submissions.none()
        _historical(result, Job.objects.filter(pk__in=inputs.values("job_id")), evidence)


def describe_references(area_key, relative_path, *, evidence=None, is_directory=False):
    """Describe exact database usage without reading or changing the filesystem."""
    result = _base()
    try:
        parts = _path(relative_path)
        evidence = _evidence(evidence)
        if not parts:
            return _presentation(_protected("Storage roots cannot be moved or removed."))
        if any(part.startswith(".qc-tool-") for part in parts):
            return _presentation(_protected("Private storage administration files cannot be managed as user files."))
        from qc_tool.database.transfers.storage_pins import describe_pins
        try:
            retained = describe_pins(area_key, relative_path, is_directory=is_directory)
        except TransferError as error:
            raise StorageReferenceError("Retained database file protection could not be checked safely.") from error
        result["reference_count"] += len(retained)
        result["references"].extend(retained[:MAX_REFERENCE_LINKS])
        if area_key in _IMMUTABLE_AREAS or str(area_key).startswith("product-"):
            result.update(_protected("Published artifacts, original specifications and boundaries are retained and cannot be moved."),
                          references=result["references"], reference_count=result["reference_count"])
            if area_key in {"published", "submissions"}:
                _published(result, relative_path, parts, evidence, is_directory)
        elif area_key == "incoming":
            _incoming(result, parts, evidence, is_directory)
        elif area_key == "jobs":
            _jobs(result, parts, evidence, is_directory)
        else:
            raise StorageReferenceError("This storage area has no file-change policy.")
        if result["reference_count"]:
            result.update(status="linked", label="Linked", protected=True, can_quarantine=False,
                          message=("A retained restore database references this path. Its files cannot be moved or removed."
                                   if retained else "Database records reference this path. Its files cannot be moved or removed."))
        result["truncated"] = result["reference_count"] > len(result["references"])
        if is_directory:
            result["can_quarantine"] = False
        return _presentation(result)
    except (DatabaseError, StorageReferenceError):
        return _presentation({**result, "status": "unavailable", "label": "Check unavailable", "checked": False,
                "protected": True, "can_quarantine": False,
                "job_matches": [], "verified_jobs": [],
                "message": "Database usage could not be checked safely. File changes remain unavailable."})


def assert_unreferenced(area_key, relative_path, *, is_directory=False):
    """Recheck immediately before a guarded move; uncertainty always denies it."""
    result = describe_references(area_key, relative_path, is_directory=is_directory)
    if not result["checked"] or not result["can_quarantine"]:
        raise StorageReferenceError(result["message"] if not is_directory else "Only individual, unreferenced files can be moved.")
    return result


def assert_restore_safe(area_key, relative_path, *, evidence):
    """Allow exact ZIP restoration after its matching records were imported.

    The caller hashes the private payload descriptor and publishes without
    replacing an existing name. A record link is never enough on its own.
    """
    try:
        evidence = _evidence(evidence)
        if evidence is None:
            raise StorageReferenceError("Verify the retained file before restoring it.")
        result = describe_references(area_key, relative_path, evidence=evidence)
        if not result["checked"]:
            raise StorageReferenceError(result["message"])
        if result["can_quarantine"]:
            return {**result, "can_restore": True}
        parts = _path(relative_path)
        if (area_key != "incoming" or len(parts) != 2 or not parts[-1].lower().endswith(".zip")
                or result["status"] != "linked"):
            raise StorageReferenceError("Linked or immutable files cannot be restored into this storage location.")
        deliveries = Delivery.objects.filter(user__username=parts[0], filename=parts[1], s3__isnull=True)
        active = deliveries.filter(is_deleted=False)
        if active.exists():
            if active.exclude(content_sha256=evidence["sha256"], size_bytes=evidence["size"]).exists():
                raise StorageReferenceError(
                    "The retained ZIP does not match every active delivery's recorded checksum and size. No file was restored."
                )
        elif not Job.objects.filter(delivery__in=deliveries, input_sha256=evidence["sha256"],
                                    delivery__size_bytes=evidence["size"]).exists():
            raise StorageReferenceError(
                "No linked historical QC job verifies this retained ZIP's checksum and size. No file was restored."
            )
        return {**result, "can_restore": True}
    except DatabaseError as exc:
        raise StorageReferenceError("Database usage could not be checked safely. No file was restored.") from exc


def _storage_link(label, area, path, *, directory):
    _path(path)
    return {"label": label, "area": area, "path": path, "directory": directory,
            "url": reverse("admin_storage" if directory else "admin_storage_file") + "?" + urlencode({"area": area, "path": path})}


def _delivery_link(delivery):
    if delivery.user_id is None or delivery.s3_id is not None:
        return None
    owner, filename = delivery.user.username, delivery.filename
    if (len(_path(owner)) != 1 or len(_path(filename)) != 1
            or not filename.lower().endswith(".zip")):
        return None
    return _storage_link("Incoming delivery ZIP", "incoming", owner + "/" + filename, directory=False)


def record_storage_links(resource, obj):
    """Return exact Admin storage locations even when files are not installed.

    Missing paths are shown by storage administration; these links never infer
    a successful historical input verification or an alternative filename.
    """
    model = getattr(resource, "model", type(obj))
    if model is not type(obj):
        return []
    links = []
    try:
        if isinstance(obj, Delivery):
            link = _delivery_link(obj)
            if link:
                links.append(link)
        elif isinstance(obj, Job):
            links.append(_storage_link("QC job files", "jobs", "job_" + obj.pk.hex, directory=True))
            link = _delivery_link(obj.delivery)
            if link:
                links.append(link)
        elif isinstance(obj, DeliverySubmission) and obj.publication_state == DeliverySubmission.PublicationState.PUBLISHED and obj.artifact_key:
            links.append(_storage_link("Published submission files", "published", obj.artifact_key, directory=True))
    except StorageReferenceError:
        # Invalid metadata cannot select another directory on disk.
        pass
    return links
