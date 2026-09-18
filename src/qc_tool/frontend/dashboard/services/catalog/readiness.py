"""Explicit manager confirmation of a complete, unchanged product scope."""

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
import secrets

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, F, Q
from django.utils import timezone

from qc_tool.frontend.dashboard.models import DeliverySubmission, Product, ProductRelease

from .sync.locks import lock_catalog_sync


class ProductReadinessError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ProductReadiness:
    is_ready: bool
    can_finalize: bool
    required_units: int
    accepted_units: int
    scope_digest: str
    label: str
    message: str
    ready_at: datetime | None
    ready_by_username: str


def product_readiness(product):
    """Evaluate every current stream, independent of paginated UI coverage.

    Each required unit needs exactly one published, accepted candidate. An
    unreviewed competing upload does not revoke the incumbent's acceptance.
    """

    return product_readiness_many((product,))[product.pk]


def product_readiness_many(products):
    """Aggregate in SQL so large plans never materialize all unit identities.

    Immutable catalog digests identify required units. The product revision
    changes with every accepted-candidate decision, binding the confirmation
    to that audited review state without scanning every candidate on each page.
    """

    products = tuple(products)
    product_ids = [product.pk for product in products]
    releases_by_product = {ident: [] for ident in product_ids}
    accepted = Q(
        product_units__submissions__publication_state=DeliverySubmission.PublicationState.PUBLISHED,
        product_units__submissions__review_state=DeliverySubmission.ReviewState.ACCEPTED,
        product_units__submissions__product_release_id=F("pk"),
    )
    releases = ProductRelease.objects.filter(
        product_id__in=product_ids, is_current=True,
    ).annotate(
        required_count=Count("product_units", distinct=True),
        accepted_count=Count("product_units", filter=accepted, distinct=True),
        accepted_candidate_count=Count("product_units__submissions", filter=accepted, distinct=True),
    ).order_by("pk").values_list(
        "product_id", "pk", "catalog_digest", "coverage_state",
        "required_count", "accepted_count", "accepted_candidate_count",
    )
    for product_id, *facts in releases:
        releases_by_product[product_id].append(facts)
    return {
        product.pk: _evaluate_readiness(product, releases_by_product[product.pk])
        for product in products
    }


def _evaluate_readiness(product, releases):
    required_units = sum(row[3] for row in releases)
    accepted_units = sum(row[4] for row in releases)
    accepted_candidates = sum(row[5] for row in releases)
    scope_digest = hashlib.sha256(json.dumps(
        {
            "version": 1, "product_id": product.pk,
            "readiness_revision": product.readiness_revision,
            "is_active": product.is_active, "releases": releases,
        },
        sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()

    complete = False
    if not product.is_active:
        label, message = "Stopped", "Restore the product before confirming readiness."
    elif not releases:
        label, message = "Delivery plan required", "Define and approve the required product units first."
    elif any(row[2] != ProductRelease.CoverageState.AUTHORITATIVE for row in releases):
        label, message = "Plan approval required", "Every current delivery plan must be approved before the product can be ready."
    elif any(row[3] == 0 for row in releases):
        label, message = "Required units missing", "Every current delivery plan must contain at least one required product unit."
    elif accepted_units != required_units or accepted_candidates != required_units:
        label, message = "In progress", "Every required product unit needs an accepted delivery before final confirmation."
    else:
        complete = True
        label, message = "Awaiting final confirmation", "All required product units have accepted deliveries. A product manager must confirm that the product is ready."

    is_ready = bool(
        complete and product.ready_at is not None
        and product.ready_scope_digest == scope_digest
    )
    if is_ready:
        label, message = "Ready", "A product manager has confirmed this product is ready."
    return ProductReadiness(
        is_ready=is_ready, can_finalize=complete and not is_ready,
        required_units=required_units, accepted_units=accepted_units,
        scope_digest=scope_digest, label=label, message=message,
        ready_at=product.ready_at if is_ready else None,
        ready_by_username=product.ready_by_username if is_ready else "",
    )


@transaction.atomic
def finalize_product(*, product_ident, actor, account_access, expected_scope_digest):
    """Confirm the exact current scope under the same lock as review/catalog edits."""

    lock_catalog_sync()
    if not account_access.can_review_product_submission(product_ident):
        raise PermissionDenied("Only assigned product managers and administrators can confirm product readiness.")
    product = Product.objects.select_for_update().get(ident=product_ident)
    readiness = product_readiness(product)
    if (
        not isinstance(expected_scope_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_scope_digest) is None
        or not secrets.compare_digest(expected_scope_digest, readiness.scope_digest)
    ):
        raise ProductReadinessError(
            "product_changed", "The product or its accepted deliveries changed. Review the current product before confirming readiness.",
        )
    if readiness.is_ready:
        return readiness
    if not readiness.can_finalize:
        raise ProductReadinessError("product_not_complete", readiness.message)
    product.ready_at = timezone.now()
    product.ready_by = actor
    product.ready_by_username = str(actor.get_username())[:150]
    product.ready_scope_digest = readiness.scope_digest
    product.save(update_fields=(
        "ready_at", "ready_by", "ready_by_username", "ready_scope_digest", "updated_at",
    ))
    LogEntry.objects.create(
        user=actor, content_type=ContentType.objects.get_for_model(Product),
        object_id=str(product.pk), object_repr=str(product)[:200], action_flag=CHANGE,
        change_message=(
            "Confirmed product ready with {} accepted required product units. Scope SHA-256 {}."
        ).format(readiness.required_units, readiness.scope_digest),
    )
    return product_readiness(product)


def invalidate_product_readiness(product_id):
    """Invalidate confirmations and stale forms, even if a prior scope is restored.

    Call inside catalog/review transactions holding the shared catalog lock.
    Existing review events and catalog audit records retain the change history.
    """

    Product.objects.filter(pk=product_id).update(
        readiness_revision=F("readiness_revision") + 1,
        ready_at=None, ready_by=None, ready_by_username="", ready_scope_digest="",
    )
