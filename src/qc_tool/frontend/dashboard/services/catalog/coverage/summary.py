"""Coverage totals for one immutable product release."""

from django.db.models import Count
from django.db.models import Exists
from django.db.models import OuterRef
from django.db.models import Q

from qc_tool.frontend.dashboard.models import DeliverySubmission
from qc_tool.frontend.dashboard.models import ProductAOI
from qc_tool.frontend.dashboard.models import ProductRelease
from qc_tool.frontend.dashboard.models import SubmissionConflict

from ..contracts import ProductCoverage


def get_product_coverage(product_release):
    """Return a denominator only for an authoritative catalog revision."""

    release = _release(product_release)
    if release.coverage_state != ProductRelease.CoverageState.AUTHORITATIVE:
        return ProductCoverage(
            release_id=release.pk,
            coverage_state=release.coverage_state,
            expected=None,
            submitted=None,
            conflicts=None,
            remaining=None,
            completion_percentage=None,
        )

    published = DeliverySubmission.objects.filter(
        product_aoi_id=OuterRef("pk"),
        publication_state=DeliverySubmission.PublicationState.PUBLISHED,
    )
    open_conflict = SubmissionConflict.objects.filter(
        product_aoi_id=OuterRef("pk"),
        state=SubmissionConflict.State.OPEN,
    )
    counts = (
        ProductAOI.objects.filter(product_release=release)
        .annotate(
            has_published=Exists(published),
            has_open_conflict=Exists(open_conflict),
        )
        .aggregate(
            expected=Count("pk"),
            submitted=Count(
                "pk",
                filter=Q(has_published=True, has_open_conflict=False),
            ),
            conflicts=Count("pk", filter=Q(has_open_conflict=True)),
        )
    )
    expected = counts["expected"]
    submitted = counts["submitted"]
    conflicts = counts["conflicts"]
    return ProductCoverage(
        release_id=release.pk,
        coverage_state=release.coverage_state,
        expected=expected,
        submitted=submitted,
        conflicts=conflicts,
        remaining=expected - submitted,
        completion_percentage=(
            round((submitted / expected) * 100, 2) if expected else 0.0
        ),
    )


def _release(product_release):
    return (
        product_release
        if isinstance(product_release, ProductRelease)
        else ProductRelease.objects.get(pk=product_release)
    )
