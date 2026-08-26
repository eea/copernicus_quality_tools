"""Product-scoped authorization for duplicate-AOI decisions."""

from ..errors import SubmissionError


def can_resolve_product_aoi(account_access, product_aoi):
    """Return whether an account may decide candidates for this product AOI."""

    if account_access.is_administrator:
        return True
    if not account_access.is_product_manager:
        return False
    granted = {value.casefold() for value in account_access.product_idents}
    if not granted:
        return False
    if product_aoi.product_release.product.ident.casefold() in granted:
        return True
    return product_aoi.product_release.definition_links.filter(
        qc_definition__product_ident__in=granted
    ).exists()


def require_resolution_scope(account_access, product_aoi):
    """Raise the stable service error when product scope is insufficient."""

    if not can_resolve_product_aoi(account_access, product_aoi):
        raise SubmissionError(
            "object_permission_denied",
            "The account cannot resolve conflicts for this product.",
            403,
        )
