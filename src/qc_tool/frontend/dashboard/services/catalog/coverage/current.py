"""Single-query coverage rows for the current Products page."""

from django.db.models import Count
from django.db.models import Q

from qc_tool.frontend.dashboard.models import DeliverySubmission
from qc_tool.frontend.dashboard.models import ProductRelease
from qc_tool.frontend.dashboard.models import SubmissionConflict


def list_current_product_coverage():
    """Return presentation-ready current release facts in one DB query."""

    return tuple(_row(release) for release in _current_releases())


def _current_releases():
    return (
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
                        )
                    )
                    & (
                        Q(aois__submission_conflict__isnull=True)
                        | Q(
                            aois__submission_conflict__state=(
                                SubmissionConflict.State.RESOLVED
                            )
                        )
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


def _row(release):
    authoritative = (
        release.coverage_state
        == ProductRelease.CoverageState.AUTHORITATIVE
    )
    expected = release.expected_count if authoritative else None
    submitted = release.submitted_count if authoritative else None
    conflicts = release.conflict_count if authoritative else None
    return {
        "ident": release.product.ident,
        "description": release.product.name,
        "release_key": release.release_key,
        "revision": release.revision,
        "coverage_state": release.coverage_state,
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
