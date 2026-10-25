"""Read-only, paginated index of submitted deliveries and their stored files.

Publication retains files; review approves or declines them. These independent
states must stay separate. Historical submitted uploads without a receipt have
no inferred approval, and a filesystem probe never verifies historical bytes.
"""

from urllib.parse import urlencode
from uuid import UUID

from django.db import DatabaseError, connections
from django.db.models import CharField, F, Q, Value
from django.db.models.functions import Cast
from django.urls import reverse

from qc_tool.frontend.dashboard.models import Delivery, DeliverySubmission
from qc_tool.frontend.dashboard.services.submissions.detail_presentation import submission_status

from . import files
from .references import record_storage_links


FILTERS = (
    ("all", "All submitted deliveries"),
    ("approved", "Approved"),
    ("pending", "Awaiting review"),
    ("conflict", "Competing submissions"),
    ("rejected", "Declined"),
    ("publishing", "Preparing files"),
    ("failed", "Publication failed"),
    ("historical", "Historical submissions"),
)
_STATUSES = frozenset(key for key, _label in FILTERS) | {"published"}


def _positive_integer(value, default, maximum=None):
    try:
        number = max(int(value), 1)
    except (TypeError, ValueError, OverflowError):
        number = default
    return min(number, maximum) if maximum else number


def _search_receipts(queryset, query):
    if not query:
        return queryset
    condition = (
        Q(delivery__filename__icontains=query)
        | Q(product_release__product__ident__icontains=query)
        | Q(product_release__product__name__icontains=query)
        | Q(product_release__release_key__icontains=query)
        | Q(product_unit_code__icontains=query)
        | Q(submitted_by_username__icontains=query)
    )
    try:
        identity = UUID(query)
    except ValueError:
        pass
    else:
        condition |= Q(pk=identity)
    return queryset.filter(condition)


def _search_historical(queryset, query):
    if query:
        queryset = queryset.filter(
            Q(filename__icontains=query)
            | Q(product_ident__icontains=query)
            | Q(product_description__icontains=query)
            | Q(product_unit_code__icontains=query)
            | Q(user__username__icontains=query)
        )
    return queryset


def _receipt_queryset(status, query):
    queryset = DeliverySubmission.objects.all()
    if status in {"approved", "pending", "conflict", "rejected"}:
        review = "accepted" if status == "approved" else status
        queryset = queryset.filter(publication_state="published", review_state=review)
    elif status == "publishing":
        queryset = queryset.filter(publication_state__in=("pending", "publishing"))
    elif status in {"failed", "published"}:
        queryset = queryset.filter(publication_state=status)
    elif status == "historical":
        queryset = queryset.none()
    return _search_receipts(queryset, query)


def _record_url(obj):
    return reverse("admin_database_record", args=[obj._meta.db_table, str(obj.pk)])


def _location(obj):
    """Probe one exact recorded location, never search filenames or walk a tree."""
    candidates = record_storage_links(None, obj)
    if not candidates:
        return {
            "available": False, "label": "No local file location recorded",
            "message": "No local retained folder is recorded for this submission.",
            "url": "", "download_url": "", "path": "", "area": "",
        }
    candidate = candidates[0]
    result = {**candidate, "available": False, "url": "", "download_url": ""}
    try:
        entry = files.inspect_entry(candidate["area"], candidate["path"])
        expected_kind = "directory" if candidate["directory"] else "file"
        if entry["kind"] != expected_kind:
            raise files.StorageError("The recorded file location has changed.")
    except files.StorageError:
        return {**result, "label": "Files unavailable", "message": (
            "The recorded location is missing, unmounted or unavailable. "
            "The database record is retained."
        )}
    if candidate["directory"]:
        message = "Retained folder found. Its contents have not been checked for completeness or integrity."
        route = "admin_storage_archive"
        label = "Retained folder available"
    else:
        message = (
            "Current upload found. Its contents have not been verified against this historical submission."
        )
        route = "admin_storage_download"
        label = "Current upload available"
    return {
        **result, "available": True, "label": label, "message": message,
        "url": candidate["url"],
        "download_url": reverse(route) + "?" + urlencode({
            "area": candidate["area"], "path": candidate["path"],
        }),
    }


def _receipt_entry(submission):
    release = submission.product_release
    published = submission.publication_state == DeliverySubmission.PublicationState.PUBLISHED
    location = _location(submission)
    status = submission_status(submission, storage_available=location["available"])
    return {
        "kind": "submission", "id": str(submission.pk), "submission_uuid": str(submission.pk),
        "delivery_id": submission.delivery_id, "filename": submission.delivery.filename,
        "product_ident": release.product.ident, "product_name": release.product.name,
        "release_key": release.release_key, "release_revision": release.revision,
        "product_unit_code": submission.product_unit_code,
        "submitted_by_username": submission.submitted_by_username,
        "submitter_label": "Submitted by", "submitter_is_snapshot": True,
        "submitted_at": submission.requested_at, "published_at": submission.published_at,
        "status": status["value"], "status_label": status["label"], "status_tone": status["tone"],
        "status_message": status["message"] if submission.review_state == "accepted" else "",
        "publication_state": submission.publication_state,
        "publication_label": submission.get_publication_state_display(),
        "review_state": submission.review_state, "review_label": submission.get_review_state_display(),
        "is_approved": published and submission.review_state == DeliverySubmission.ReviewState.ACCEPTED,
        "release_is_current": release.is_current,
        "approval_scope": "Current delivery plan" if release.is_current else "Earlier delivery plan",
        "is_historical": False, "record_url": _record_url(submission),
        "location": location, "publication_files": location,
        "files_url": location["url"], "download_url": location["download_url"],
    }


def _historical_entry(delivery):
    location = _location(delivery)
    return {
        "kind": "historical", "id": str(delivery.pk), "submission_uuid": "",
        "delivery_id": delivery.pk, "filename": delivery.filename,
        "product_ident": delivery.product_ident or "", "product_name": delivery.product_description or "",
        "release_key": "", "release_revision": None,
        "product_unit_code": delivery.product_unit_code or "",
        "submitted_by_username": delivery.user.username if delivery.user_id else "",
        "submitter_label": "Upload owner", "submitter_is_snapshot": False,
        "submitted_at": delivery.date_submitted, "published_at": None,
        "status": "historical", "status_label": "Historical submission",
        "status_tone": "muted", "status_message": "No retained review decision is recorded for this historical submission.",
        "publication_state": "historical", "publication_label": "No publication receipt",
        "review_state": "unknown", "review_label": "Approval unknown", "is_approved": False,
        "release_is_current": False, "approval_scope": "Approval unknown",
        "is_historical": True, "record_url": _record_url(delivery),
        "location": location, "publication_files": location,
        "files_url": location["url"], "download_url": location["download_url"],
    }


def _index_key(kind, identity):
    # SQLite stores UUIDs without hyphens, PostgreSQL casts them with hyphens.
    return kind, str(UUID(identity)) if kind == "submission" else str(identity)


def _index_page(index, start, stop):
    """Keep the ORM's bound compound query recognizable as a read on PostgreSQL.

    Django parenthesizes PostgreSQL UNION branches. An outer SELECT gives the
    maintenance read guard an unambiguous statement type without weakening it.
    The compiler retains all user input as bound parameters; only fixed SQL and
    identifiers are added here. Ordering outside the subquery stays explicit.
    """
    database = connections[index.db]
    sql, params = index[start:stop].query.get_compiler(using=index.db).as_sql()
    columns = ("inventory_kind", "inventory_id", "inventory_date")
    order = ", ".join(
        database.ops.quote_name(name) + direction
        for name, direction in (("inventory_date", " DESC"), ("inventory_kind", " ASC"), ("inventory_id", " ASC"))
    )
    with database.cursor() as cursor:
        cursor.execute(f"SELECT * FROM ({sql}) AS storage_submission_page ORDER BY {order}", params)
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def inventory(*, query="", status="all", page=1, page_size=25):
    """Return all submitted receipts plus legacy submissions, with bounded I/O.

    SQL merges only identifiers and dates before pagination. Hydration uses at
    most two additional queries, and only visible rows have file probes. A
    regular upload without a submission timestamp or receipt is not submitted.
    """
    query = str(query or "").strip()[:150]
    status = status if isinstance(status, str) and status in _STATUSES else "all"
    page = _positive_integer(page, 1)
    page_size = _positive_integer(page_size, 25, 100)
    base = {
        "available": True, "message": "", "entries": [], "query": query, "status": status,
        "filters": [{"key": key, "label": label} for key, label in FILTERS],
        "page": 1, "page_size": page_size, "page_count": 1,
        "total": 0, "total_count": 0, "has_previous": False, "has_next": False,
    }
    try:
        receipts = _receipt_queryset(status, query)
        historical = Delivery.objects.filter(date_submitted__isnull=False, submission__isnull=True)
        historical = _search_historical(historical, query) if status in {"all", "historical"} else historical.none()
        receipt_index = receipts.order_by().annotate(
            inventory_kind=Value("submission", output_field=CharField()),
            inventory_id=Cast("pk", output_field=CharField()), inventory_date=F("requested_at"),
        ).values("inventory_kind", "inventory_id", "inventory_date")
        historical_index = historical.order_by().annotate(
            inventory_kind=Value("historical", output_field=CharField()),
            inventory_id=Cast("pk", output_field=CharField()), inventory_date=F("date_submitted"),
        ).values("inventory_kind", "inventory_id", "inventory_date")
        index = receipt_index.union(historical_index).order_by(
            "-inventory_date", "inventory_kind", "inventory_id",
        )
        total = index.count()
        page_count = max((total + page_size - 1) // page_size, 1)
        page = min(page, page_count)
        selected = _index_page(index, (page - 1) * page_size, page * page_size) if total else []
        receipt_ids = [item["inventory_id"] for item in selected if item["inventory_kind"] == "submission"]
        historical_ids = [item["inventory_id"] for item in selected if item["inventory_kind"] == "historical"]
        hydrated = {}
        if receipt_ids:
            for submission in receipts.filter(pk__in=receipt_ids).select_related("delivery", "product_release__product"):
                hydrated[("submission", str(submission.pk))] = _receipt_entry(submission)
        if historical_ids:
            for delivery in historical.filter(pk__in=historical_ids).select_related("user"):
                hydrated[("historical", str(delivery.pk))] = _historical_entry(delivery)
        entries = [hydrated[key] for item in selected
                   if (key := _index_key(item["inventory_kind"], item["inventory_id"])) in hydrated]
        return {
            **base, "entries": entries, "page": page, "page_count": page_count,
            "total": total, "total_count": total, "has_previous": page > 1, "has_next": page < page_count,
        }
    except DatabaseError:
        return {**base, "available": False, "message": (
            "Submitted deliveries could not be read from the active database. "
            "No records or files were changed. You can still browse configured storage locations."
        )}
