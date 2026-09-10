"""Product-scoped authorization for duplicate-AOI decisions."""

from ..errors import SubmissionError


def can_resolve_product_aoi(account_access, product_aoi):
    """Return whether an account may decide candidates for this product AOI."""

    return account_access.can_review_product_submission(
        product_aoi.product_release.product.ident
    )


def require_resolution_scope(account_access, product_aoi):
    """Raise the stable service error when product scope is insufficient."""

    if not can_resolve_product_aoi(account_access, product_aoi):
        raise SubmissionError(
            "object_permission_denied",
            "The account cannot review submissions for this product.",
            403,
        )
