from django.db import transaction

from qc_tool.frontend.accounts.models import UserProductGrant


@transaction.atomic
def create_product_grant(*, user, product_ident, created_by=None):
    """Assign a business-product or exact QC-definition scope to any user.

    Assignments scope existing role capabilities; they do not grant a role.
    """

    grant = UserProductGrant(
        user=user,
        product_ident=product_ident,
        created_by=created_by,
    )
    return save_product_grant(grant, created_by=created_by)


@transaction.atomic
def save_product_grant(grant, *, created_by=None):
    """Validate an admin or service assignment and preserve its creator audit.

    The caller authorizes who may administer assignments. This shared write
    path validates canonical business-product or QC-definition identifiers and
    duplicate grants for default users and product managers alike. Textual
    identifiers preserve definition-only and existing assignments;
    they are not foreign keys to business products.
    """

    if grant._state.adding:
        grant.created_by = created_by
    grant.full_clean()
    grant.save()
    return grant
