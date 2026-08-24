from django.db import transaction

from qc_tool.frontend.accounts.models import UserProductGrant


@transaction.atomic
def create_product_grant(*, user, product_ident, created_by=None):
    """Validate and persist one new canonical product grant."""

    grant = UserProductGrant(
        user=user,
        product_ident=product_ident,
        created_by=created_by,
    )
    grant.full_clean()
    grant.save()
    return grant
