"""Retained catalog history and bounded product presentation edits."""

from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db.models import Q

from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard.models import Product
from qc_tool.frontend.dashboard.models import ProductUnit
from qc_tool.frontend.dashboard.models import ProductRelease
from qc_tool.frontend.dashboard.models import ProductReleaseDefinition
from qc_tool.frontend.dashboard.models import QcDefinition
from qc_tool.frontend.dashboard.services.catalog.product_metadata import (
    METADATA_FIELDS, metadata_version, update_product_metadata, validate_product_metadata,
)

from .scope import release_scope
from .scope import ScopedCatalogHistoryAdmin


class ProductMetadataForm(forms.ModelForm):
    metadata_version = forms.RegexField(regex=r"\A[0-9a-f]{64}\Z", widget=forms.HiddenInput)

    class Meta:
        model = Product
        fields = METADATA_FIELDS

    def __init__(self, *args, actor=None, **kwargs):
        self.actor = actor
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.initial["metadata_version"] = metadata_version(self.instance)

    def clean(self):
        cleaned = super().clean()
        protected = {name for field in Product._meta.concrete_fields
                     for name in (field.name, field.attname) if field.name not in METADATA_FIELDS}
        if protected.intersection(self.data):
            raise ValidationError("Only the product name and description can be changed here.")
        if self.instance.pk and all(name in cleaned for name in (*METADATA_FIELDS, "metadata_version")):
            try:
                validate_product_metadata(
                    product_id=self.instance.pk, actor=self.actor,
                    name=cleaned["name"], description=cleaned["description"],
                    expected_version=cleaned["metadata_version"],
                )
            except ValidationError as error:
                # A protected stored field may also fail full_clean(); it has
                # no editable form field, so display a safe non-field error.
                raise ValidationError(error.messages) from error
        return cleaned


@admin.register(Product)
class ProductAdmin(ScopedCatalogHistoryAdmin):
    form = ProductMetadataForm
    list_display = ("ident", "name", "updated_at")
    search_fields = ("ident", "name", "description")
    readonly_fields = tuple(field.name for field in Product._meta.fields)

    def has_change_permission(self, request, obj=None):
        return access_for_request(request).is_administrator

    def get_readonly_fields(self, request, obj=None):
        if self.has_change_permission(request, obj):
            return tuple(field for field in self.readonly_fields if field not in METADATA_FIELDS)
        return self.readonly_fields

    def get_fieldsets(self, request, obj=None):
        metadata_fields = (*METADATA_FIELDS, "metadata_version") if self.has_change_permission(request, obj) else METADATA_FIELDS
        return (
            ("Product metadata", {"fields": metadata_fields}),
            ("Protected product details", {
                "fields": tuple(field for field in self.readonly_fields if field not in METADATA_FIELDS),
                "classes": ("collapse",),
            }),
        )

    def get_form(self, request, obj=None, **kwargs):
        base_form = super().get_form(request, obj, **kwargs)

        class RequestProductMetadataForm(base_form):
            def __init__(self, *args, **form_kwargs):
                super().__init__(*args, actor=request.user, **form_kwargs)

        return RequestProductMetadataForm

    def save_model(self, request, obj, form, change):
        saved = update_product_metadata(
            product_id=obj.pk, actor=request.user,
            name=form.cleaned_data["name"], description=form.cleaned_data["description"],
            expected_version=form.cleaned_data["metadata_version"],
        )
        for field in obj._meta.concrete_fields:
            setattr(obj, field.attname, getattr(saved, field.attname))

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
