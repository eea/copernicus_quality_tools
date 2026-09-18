"""Map product sources to immutable, template-safe values."""

from qc_tool.frontend.dashboard.services.catalog import (
    get_remaining_product_unit_codes,
)
from qc_tool.frontend.dashboard.services.catalog import (
    list_current_product_coverage,
)

from .contracts import ProductCoverageSummary
from .contracts import ProductDefinitionSummary
from .contracts import ProductDetail
from .contracts import ProductReleaseDetail
from .contracts import ProductReleaseSummary
from .contracts import QualityCheckSummary


REMAINING_UNIT_PAGE_SIZE = 200


def managed_product_detail(
    releases,
    *,
    include_coverage,
    releases_truncated,
):
    coverage = _coverage_by_release(releases, include=include_coverage)
    release_details = tuple(
        _managed_release_detail(
            release,
            coverage=coverage.get(release.pk),
            include_coverage=include_coverage,
        )
        for release in releases
    )
    product = releases[0].product
    return ProductDetail(
        ident=product.ident,
        name=product.name,
        description=product.description or releases[0].description,
        managed=True,
        releases=release_details,
        releases_truncated=releases_truncated,
        definitions=(),
        quality_checks=None,
    )


def _managed_release_detail(release, *, coverage, include_coverage):
    definition_links = tuple(release.definition_links.all())
    definitions = tuple(
        _definition_summary(link.qc_definition, primary=link.is_primary)
        for link in definition_links
    )
    remaining_units = (
        get_remaining_product_unit_codes(
            release,
            limit=REMAINING_UNIT_PAGE_SIZE,
        )
        if include_coverage and coverage is not None
        else None
    )
    return ProductReleaseDetail(
        release=ProductReleaseSummary(
            key=release.release_key,
            revision=release.revision,
            description=release.description,
            coverage_state=release.coverage_state,
            coverage_state_label=release.get_coverage_state_display(),
            approved_at=release.approved_at,
        ),
        definitions=definitions,
        quality_checks=_quality_checks(_primary_document(definition_links)),
        coverage=coverage,
        remaining_units=remaining_units,
        remaining_units_truncated=bool(
            remaining_units is not None
            and coverage is not None
            and coverage.remaining is not None
            and coverage.remaining > len(remaining_units)
        ),
    )


def _coverage_by_release(releases, *, include):
    if not include:
        return {}
    release_ids = tuple(release.pk for release in releases)
    return {
        row["release_id"]: ProductCoverageSummary(
            state=row["coverage_state"],
            declared_expected=row["declared_expected"],
            expected=row["expected"],
            accepted=row["accepted"],
            conflicts=row["conflicts"],
            remaining=row["remaining"],
            completion_percentage=row["completion_percentage"],
        )
        for row in list_current_product_coverage(
            release_ids=release_ids, include_inactive=True,
        )
    }


def _definition_summary(definition, *, primary):
    return ProductDefinitionSummary(
        ident=definition.product_ident,
        description=definition.description,
        digest=definition.digest,
        is_primary=primary,
    )


def _primary_document(definition_links):
    primary = next(
        (link for link in definition_links if link.is_primary),
        definition_links[0] if definition_links else None,
    )
    return primary.qc_definition.document if primary is not None else None


def _quality_checks(document):
    steps = document.get("steps") if isinstance(document, dict) else None
    if not isinstance(steps, list):
        return None
    required = sum(
        1
        for step in steps
        if isinstance(step, dict) and step.get("required") == 1
    )
    return QualityCheckSummary(
        total=len(steps),
        required=required,
        optional=len(steps) - required,
    )
