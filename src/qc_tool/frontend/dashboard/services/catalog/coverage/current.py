"""Single-query coverage rows for the current Products page."""

from django.db.models import Count
from django.db.models import Q

from qc_tool.frontend.dashboard.models import DeliverySubmission
from qc_tool.frontend.dashboard.models import ProductRelease
from qc_tool.frontend.dashboard.models import SubmissionConflict


MAX_FILTERED_RELEASES = 50


def list_current_product_coverage(*, release_ids=None, include_inactive=False):
    """Return presentation-ready current release facts in one DB query."""

    return tuple(
        _row(release)
        for release in _current_releases(
            release_ids=release_ids, include_inactive=include_inactive
        )
    )


def _current_releases(*, release_ids, include_inactive):
    queryset = (
        ProductRelease.objects.filter(is_current=True)
        .select_related("product")
        .annotate(
            expected_count=Count("aois", distinct=True),
            submitted_count=Count(
                "aois",
                filter=(
                    Q(
                        aois__submissions__publication_state=(
                            DeliverySubmission.PublicationState.PUBLISHED
                        ),
                        aois__submissions__review_state=(
                            DeliverySubmission.ReviewState.ACCEPTED
                        ),
                    )
                ),
                distinct=True,
            ),
            conflict_count=Count(
                "aois",
                filter=Q(
                    aois__submission_conflict__state=(
                        SubmissionConflict.State.OPEN
                    )
                ),
                distinct=True,
            ),
        )
        .order_by("product__name", "release_key")
    )
    if not include_inactive:
        queryset = queryset.filter(product__is_active=True)
    if release_ids is None:
        return queryset
    release_ids = tuple(release_ids)
    if (
        len(release_ids) > MAX_FILTERED_RELEASES
        or any(
            isinstance(release_id, bool)
            or not isinstance(release_id, int)
            or release_id < 1
            for release_id in release_ids
        )
    ):
        raise ValueError("release_ids are outside the supported bounds")
    return queryset.filter(pk__in=release_ids)


def _row(release):
    authoritative = (
        release.coverage_state
        == ProductRelease.CoverageState.AUTHORITATIVE
    )
    expected = release.expected_count if authoritative else None
    declared_expected = (
        release.expected_count
        if release.coverage_state in (
            ProductRelease.CoverageState.DRAFT,
            ProductRelease.CoverageState.AUTHORITATIVE,
        )
        else None
    )
    submitted = release.submitted_count if authoritative else None
    conflicts = release.conflict_count if authoritative else None
    return {
        "release_id": release.pk,
        "ident": release.product.ident,
        "is_active": release.product.is_active,
        "description": release.product.name,
        "release_key": release.release_key,
        "revision": release.revision,
        "coverage_state": release.coverage_state,
        "declared_expected": declared_expected,
        "expected": expected,
        "submitted": submitted,
        "conflicts": conflicts,
        "remaining": expected - submitted if authoritative else None,
        "completion_percentage": _completion(
            expected,
            submitted,
            authoritative=authoritative,
        ),
    }


def _completion(expected, submitted, *, authoritative):
    if not authoritative:
        return None
    return round((submitted / expected) * 100, 2) if expected else 0.0
