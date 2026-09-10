import json
import logging
from pathlib import Path

from django.core.exceptions import ValidationError

from qc_tool.common import INVALID_PRODUCT_DESCRIPTION
from qc_tool.common import PRODUCT_FILENAME_REGEX
from qc_tool.common import get_product_descriptions
from qc_tool.common import product_definition_directories
from qc_tool.product_security import canonical_product_ident
from qc_tool.product_security import normalize_product_ident


UNAVAILABLE_PRODUCT_LABEL = "unavailable legacy product"
logger = logging.getLogger(__name__)


class ProductCatalogUnavailable(Exception):
    """The configured product definitions cannot currently be read."""


def available_product_descriptions():
    """Return canonical lowercase definition stems mapped to descriptions."""

    try:
        descriptions = get_product_descriptions()
    except (json.JSONDecodeError, KeyError, TypeError, UnicodeDecodeError):
        return _scan_product_descriptions()
    except Exception as error:
        raise ProductCatalogUnavailable(
            "Configured product definitions are unavailable."
        ) from error
    if not _descriptions_are_valid(descriptions):
        return _scan_product_descriptions()
    return descriptions


def _descriptions_are_valid(descriptions):
    return bool(
        isinstance(descriptions, dict)
        and all(
            isinstance(product_ident, str)
            and product_ident
            and canonical_product_ident(product_ident) is not None
            and isinstance(description, str)
            and description.strip()
            for product_ident, description in descriptions.items()
        )
    )


def _scan_product_descriptions():
    """Load definitions independently so one invalid file cannot hide others."""

    try:
        product_dirs = tuple(product_definition_directories())
    except (KeyError, TypeError) as error:
        raise ProductCatalogUnavailable(
            "Product definition directories are not configured."
        ) from error
    if not product_dirs:
        raise ProductCatalogUnavailable(
            "Product definition directories are not configured."
        )

    descriptions = {}
    for configured_dir in reversed(product_dirs):
        product_dir = Path(configured_dir)
        try:
            filepaths = tuple(product_dir.iterdir())
        except OSError as error:
            raise ProductCatalogUnavailable(
                f"Product definition directory is unavailable: {product_dir}"
            ) from error

        for filepath in filepaths:
            if not filepath.is_file():
                continue
            if PRODUCT_FILENAME_REGEX.match(filepath.name) is None:
                continue

            product_ident = normalize_product_ident(filepath.stem)
            if product_ident is None:
                logger.warning(
                    "Ignoring product definition with an unroutable identifier: %s",
                    filepath,
                )
                continue
            try:
                definition = json.loads(filepath.read_text())
                description = definition["description"]
                if not isinstance(description, str) or not description.strip():
                    raise ValueError("description must be a non-empty string")
            except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
                logger.warning(
                    "Invalid product definition %s: %s",
                    filepath,
                    error,
                )
                description = INVALID_PRODUCT_DESCRIPTION
            descriptions[product_ident] = description

    return descriptions


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
    """Grant selectors include catalog groups without adding them to QC choices."""

    from qc_tool.frontend.dashboard.models import Product

    products = dict(Product.objects.filter(is_active=True).values_list("ident", "name"))
    try:
        definitions = available_product_descriptions()
    except ProductCatalogUnavailable:
        if not products:
            raise
        definitions = {}
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
