"""Shared product-scope policy for read-only domain history admins."""

from django.contrib import admin
from django.db.models import Q

from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard.services.submissions import (
    can_resolve_product_aoi,
)


class ScopedCatalogHistoryAdmin(admin.ModelAdmin):
    """Read-only admin base explicitly available to product managers."""

    def has_module_permission(self, request):
        access = access_for_request(request)
        return bool(access.is_administrator or access.is_product_manager)

    def has_view_permission(self, request, obj=None):
        access = access_for_request(request)
        if access.is_administrator:
            return True
        if not access.is_product_manager:
            return False
        if obj is None:
            return True
        product_aoi = self._product_aoi_for_object(obj)
        if product_aoi is not None:
            return can_resolve_product_aoi(access, product_aoi)
        product_idents = self._product_idents_for_object(obj)
        return bool(
            {value.casefold() for value in access.product_idents}
            & {value.casefold() for value in product_idents}
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def _product_aoi_for_object(self, _obj):
        return None

    def _product_idents_for_object(self, _obj):
        return ()


def release_scope(queryset, request, *, prefix=""):
    """Restrict release-backed rows to administrator or product grants."""

    access = access_for_request(request)
    if access.is_administrator:
        return queryset
    if not access.is_product_manager or not access.product_idents:
        return queryset.none()
    granted = tuple(value.casefold() for value in access.product_idents)
    return queryset.filter(
        Q(**{f"{prefix}product__ident__in": granted})
        | Q(
            **{
                f"{prefix}definition_links__qc_definition__product_ident__in": (
                    granted
                )
            }
        )
    ).distinct()
