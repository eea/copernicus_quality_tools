"""Product-scoped authorization for duplicate-product unit decisions."""

from ..errors import SubmissionError


def can_resolve_product_unit(account_access, product_unit):
    """Return whether an account may decide candidates for this product product unit."""

    return account_access.can_review_product_submission(
        product_unit.product_release.product.ident
    )


def require_resolution_scope(account_access, product_unit):
    """Raise the stable service error when product scope is insufficient."""

    if not can_resolve_product_unit(account_access, product_unit):
        raise SubmissionError(
            "object_permission_denied",
            "The account cannot review submissions for this product.",
            403,
        )
