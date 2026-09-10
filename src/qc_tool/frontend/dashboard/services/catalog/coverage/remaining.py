"""Bounded stable pages of AOIs still needing an accepted candidate."""

from django.db.models import Exists
from django.db.models import OuterRef

from qc_tool.frontend.dashboard.models import DeliverySubmission
from qc_tool.frontend.dashboard.models import ProductAOI
from qc_tool.frontend.dashboard.models import ProductRelease


def get_remaining_aoi_codes(product_release, *, offset=0, limit=200):
    """Return AOIs without a safely published, approved candidate."""

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
        review_state=DeliverySubmission.ReviewState.ACCEPTED,
    )
    return tuple(
        ProductAOI.objects.filter(product_release=release)
        .annotate(
            has_published=Exists(published),
        )
        .filter(has_published=False)
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
