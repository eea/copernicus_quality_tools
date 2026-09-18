"""Read-only catalog history for administrators and scoped managers."""

from django.contrib import admin
from django.db.models import Q

from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard.models import Product
from qc_tool.frontend.dashboard.models import ProductUnit
from qc_tool.frontend.dashboard.models import ProductRelease
from qc_tool.frontend.dashboard.models import ProductReleaseDefinition
from qc_tool.frontend.dashboard.models import QcDefinition

from .scope import release_scope
from .scope import ScopedCatalogHistoryAdmin


@admin.register(Product)
class ProductAdmin(ScopedCatalogHistoryAdmin):
    list_display = ("ident", "name", "updated_at")
    search_fields = ("ident", "name", "description")
    readonly_fields = tuple(field.name for field in Product._meta.fields)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        access = access_for_request(request)
        if access.is_administrator:
            return queryset
        granted = tuple(value.casefold() for value in access.product_idents)
        return queryset.filter(
            Q(ident__in=granted)
            | Q(
                releases__definition_links__qc_definition__product_ident__in=(
                    granted
                )
            )
        ).distinct()

    def _product_idents_for_object(self, obj):
        return (obj.ident,)


@admin.register(ProductRelease)
class ProductReleaseAdmin(ScopedCatalogHistoryAdmin):
    list_display = (
        "release_key",
        "revision",
        "product",
        "coverage_state",
        "is_current",
        "approved_at",
    )
    list_filter = ("coverage_state", "is_current")
    search_fields = ("release_key", "product__ident", "description")
    readonly_fields = tuple(field.name for field in ProductRelease._meta.fields)

    def get_queryset(self, request):
        return release_scope(super().get_queryset(request), request)

    def _product_idents_for_object(self, obj):
        return tuple(
            obj.definition_links.values_list(
                "qc_definition__product_ident", flat=True
            )
        ) + (obj.product.ident,)


@admin.register(QcDefinition)
class QcDefinitionAdmin(ScopedCatalogHistoryAdmin):
    list_display = (
        "product_ident",
        "short_digest",
        "description",
        "imported_at",
    )
    search_fields = ("product_ident", "description", "digest")
    fields = (
        "product_ident",
        "digest",
        "description",
        "source_path",
        "imported_at",
    )
    readonly_fields = fields

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        access = access_for_request(request)
        if access.is_administrator:
            return queryset
        return queryset.filter(
            product_ident__in=tuple(access.product_idents)
        )

    def _product_idents_for_object(self, obj):
        return (obj.product_ident,)

    @admin.display(description="Digest")
    def short_digest(self, obj):
        return obj.digest[:12]


@admin.register(ProductReleaseDefinition)
class ProductReleaseDefinitionAdmin(ScopedCatalogHistoryAdmin):
    list_display = ("product_release", "qc_definition", "is_primary")
    readonly_fields = tuple(
        field.name for field in ProductReleaseDefinition._meta.fields
    )

    def get_queryset(self, request):
        return release_scope(
            super().get_queryset(request),
            request,
            prefix="product_release__",
        )

    def _product_idents_for_object(self, obj):
        return (obj.qc_definition.product_ident,)


@admin.register(ProductUnit)
class ProductUnitAdmin(ScopedCatalogHistoryAdmin):
    list_display = (
        "product_unit_code",
        "product_release",
        "provenance",
        "created_at",
    )
    search_fields = ("product_unit_code", "product_release__release_key")
    readonly_fields = tuple(field.name for field in ProductUnit._meta.fields)

    def get_queryset(self, request):
        return release_scope(
            super().get_queryset(request).select_related(
                "product_release__product"
            ),
            request,
            prefix="product_release__",
        )

    def _product_unit_for_object(self, obj):
        return obj
