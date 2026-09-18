from django.core.exceptions import ValidationError
from django.db import DatabaseError


UNAVAILABLE_PRODUCT_LABEL = "unavailable legacy product"


class ProductCatalogUnavailable(Exception):
    """The managed product catalog cannot currently be read."""


def _available_definition_links():
    from qc_tool.frontend.dashboard.models import ProductReleaseDefinition

    return ProductReleaseDefinition.objects.filter(
        product_release__is_current=True,
        product_release__product__is_active=True,
    ).exclude(product_release__coverage_state="retired")


def available_product_descriptions():
    """Return executable specifications explicitly added to the active catalog.

    Files shipped with the application are recipes, not catalog registrations.
    Only a current managed release makes its stored definitions available to
    user workflows. Historical revisions and archived products stay unavailable.
    """

    try:
        return dict(_available_definition_links().order_by(
            "qc_definition__imported_at", "qc_definition_id",
        ).values_list(
            "qc_definition__product_ident", "qc_definition__description",
        ))
    except DatabaseError as error:
        raise ProductCatalogUnavailable(
            "The managed product catalog is unavailable."
        ) from error


def available_product_idents():
    return frozenset(available_product_descriptions())


def product_ident_choices(*, include=()):
    """Return current choices plus labeled stored values no longer available."""

    descriptions = grantable_product_descriptions()
    choices = {
        product_ident: f"{product_ident} — {description}"
        for product_ident, description in descriptions.items()
    }
    for product_ident in include:
        if product_ident and product_ident not in choices:
            choices[product_ident] = (
                f"{product_ident} — {UNAVAILABLE_PRODUCT_LABEL}"
            )
    return tuple(sorted(choices.items()))


def validate_new_product_ident(product_ident):
    """Accept canonical active products or explicitly scoped QC definitions."""

    if product_ident not in grantable_product_descriptions():
        raise ValidationError(
            {
                "product_ident": (
                    "Select an available canonical product or QC definition."
                )
            }
        )
    return product_ident


def grantable_product_descriptions():
    """Grant selectors include active parent products and their QC definitions."""

    definitions = available_product_descriptions()
    try:
        products = dict(_available_definition_links().values_list(
            "product_release__product__ident", "product_release__product__name",
        ))
    except DatabaseError as error:
        raise ProductCatalogUnavailable(
            "The managed product catalog is unavailable."
        ) from error
    return {**definitions, **products}


def catalog_product_scope(product_idents):
    """Resolve recipe grants into parent metadata and complete product scopes.

    Product grants remain exact. A recipe grant can reveal its parent metadata,
    but cannot expose another stream's aggregate results or review decisions.
    """

    from qc_tool.frontend.dashboard.models import ProductRelease

    granted = frozenset(product_idents)
    if not granted:
        return granted, granted, granted
    parents = ProductRelease.objects.filter(
        is_current=True,
        definition_links__qc_definition__product_ident__in=granted,
    ).values_list("product_id", flat=True)
    scopes = {}
    history_scopes = {}
    rows = ProductRelease.objects.filter(
        product_id__in=parents,
    ).values_list("product__ident", "is_current", "definition_links__qc_definition__product_ident")
    for product_ident, is_current, definition_ident in rows:
        history_scopes.setdefault(product_ident, set()).add(definition_ident)
        if is_current:
            scopes.setdefault(product_ident, set()).add(definition_ident)
    browsable = granted | frozenset(scopes)
    complete = granted | frozenset(
        product_ident for product_ident, definitions in scopes.items()
        if definitions and None not in definitions and definitions.issubset(granted)
    )
    reviewable = granted | frozenset(
        product_ident for product_ident, definitions in history_scopes.items()
        if definitions and None not in definitions and definitions.issubset(granted)
    )
    return browsable, complete, reviewable


def operable_product_scope(product_idents):
    """Include executable recipes only when their current release is unambiguous.

    Shared recipes must not turn a parent assignment into access to another
    product. Job creation also checks the actual snapshotted release.
    """

    from qc_tool.frontend.dashboard.models import ProductRelease

    granted = frozenset(product_idents)
    if not granted:
        return granted
    recipes = {}
    for recipe, release_id, parent, active in ProductRelease.objects.filter(
        is_current=True,
    ).values_list(
        "definition_links__qc_definition__product_ident", "pk",
        "product__ident", "product__is_active",
    ):
        if recipe is not None:
            recipes.setdefault(recipe, {})[release_id] = (parent, active)
    return granted | frozenset(
        recipe for recipe, releases in recipes.items()
        if len(releases) == 1
        and any(active and parent in granted for parent, active in releases.values())
    )
