from django.core.exceptions import PermissionDenied, ValidationError
from django.db import router, transaction

from qc_tool.frontend.accounts.authorization import access_for
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.accounts.services import products
from qc_tool.frontend.accounts.services.admin_users import serialized_admin_user_change


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


def add_product_grants(*, user, product_idents, created_by):
    """Add exact, currently available specifications in one Admin transaction.

    Resolve the catalog once for the whole selection. Existing assignments and
    their creator audit stay intact; selecting a family never stores a wildcard
    or grants access to specifications added later.
    """
    using = user._state.db or router.db_for_write(UserProductGrant, instance=user)
    with serialized_admin_user_change(using=using):
        permission = f"{UserProductGrant._meta.app_label}.add_userproductgrant"
        if not access_for(created_by).is_administrator or not created_by.has_perm(permission):
            raise PermissionDenied
        if not user.pk:
            raise ValidationError("Save the user before assigning specifications.")
        target = type(user)._default_manager.using(using).select_for_update().get(pk=user.pk)
        if target.is_superuser and not created_by.is_superuser:
            raise PermissionDenied
        if not isinstance(product_idents, (list, tuple, set, frozenset)) or any(
            not isinstance(ident, str) for ident in product_idents
        ):
            raise ValidationError("Choose existing product specifications.")
        selected = set(product_idents)
        if not selected:
            return ()
        try:
            available = products.available_product_descriptions()
        except products.ProductCatalogUnavailable as error:
            raise ValidationError(
                "The product catalog is unavailable; specifications cannot be assigned."
            ) from error
        if selected.difference(available):
            raise ValidationError("Choose existing product specifications.")
        # Apply the model field validators once per identifier without repeating
        # full catalog/foreign-key/uniqueness queries for every selected row.
        field = UserProductGrant._meta.get_field("product_ident")
        for ident in selected:
            field.clean(ident, None)
        existing = set(UserProductGrant.objects.using(using).filter(
            user_id=target.pk, product_ident__in=selected,
        ).values_list("product_ident", flat=True))
        grants = [UserProductGrant(user_id=target.pk, product_ident=ident, created_by=created_by)
                  for ident in sorted(selected.difference(existing))]
        return tuple(UserProductGrant.objects.using(using).bulk_create(grants))
