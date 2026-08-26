"""Bounded stable pages of AOIs still needing an accepted candidate."""

from django.db.models import Exists
from django.db.models import OuterRef
from django.db.models import Q

from qc_tool.frontend.dashboard.models import DeliverySubmission
from qc_tool.frontend.dashboard.models import ProductAOI
from qc_tool.frontend.dashboard.models import ProductRelease
from qc_tool.frontend.dashboard.models import SubmissionConflict


def get_remaining_aoi_codes(product_release, *, offset=0, limit=200):
    """Return AOIs without a published, conflict-free candidate."""

    release = (
        product_release
        if isinstance(product_release, ProductRelease)
        else ProductRelease.objects.get(pk=product_release)
    )
    if release.coverage_state != ProductRelease.CoverageState.AUTHORITATIVE:
        return None
    _validate_page(offset, limit)
    published = DeliverySubmission.objects.filter(
        product_aoi_id=OuterRef("pk"),
        publication_state=DeliverySubmission.PublicationState.PUBLISHED,
    )
    open_conflict = SubmissionConflict.objects.filter(
        product_aoi_id=OuterRef("pk"),
        state=SubmissionConflict.State.OPEN,
    )
    return tuple(
        ProductAOI.objects.filter(product_release=release)
        .annotate(
            has_published=Exists(published),
            has_open_conflict=Exists(open_conflict),
        )
        .filter(Q(has_published=False) | Q(has_open_conflict=True))
        .order_by("aoi_code")
        .values_list("aoi_code", flat=True)[offset : offset + limit]
    )


def _validate_page(offset, limit):
    if (
        isinstance(offset, bool)
        or not isinstance(offset, int)
        or offset < 0
        or isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= 1_000
    ):
        raise ValueError("offset/limit are outside the supported bounds")
