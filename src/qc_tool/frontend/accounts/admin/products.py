import logging

from django import forms
from django.contrib import admin
from django.forms.models import BaseInlineFormSet

from qc_tool.frontend.accounts.models import UserProductGrant


CATALOG_UNAVAILABLE_MESSAGE = (
    "The product catalog is unavailable; product grants cannot be added or "
    "changed."
)
logger = logging.getLogger(__name__)


def _catalog_choices():
    """Read business-product and QC-definition scopes for an admin formset."""

    from qc_tool.frontend.accounts.services.products import (
        ProductCatalogUnavailable,
    )
    from qc_tool.frontend.accounts.services.products import product_ident_choices

    try:
        return product_ident_choices(), False
    except ProductCatalogUnavailable:
        logger.warning(
            "Product grant choices could not be loaded from the managed catalog.",
            exc_info=True,
        )
        return (), True


class UserProductGrantForm(forms.ModelForm):
    product_ident = forms.ChoiceField(
        choices=(),
        label="Product or QC definition",
        help_text=(
            "Choose a product for its full scope, or a QC definition for only "
            "that definition's scope. Add one row per assignment. "
            "Default users can upload deliveries, run QC, and submit their own "
            "deliveries for assigned products. Review decisions require the "
            "product-manager or administrator role."
        ),
    )

    class Meta:
        model = UserProductGrant
        fields = ("product_ident",)

    def __init__(
        self,
        *args,
        catalog_choices=None,
        catalog_unavailable=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        if catalog_choices is None:
            catalog_choices, catalog_unavailable = _catalog_choices()

        current = self.instance.product_ident if self.instance.pk else None
        choices = dict(catalog_choices)
        if current and current not in choices:
            choices[current] = f"{current} — unavailable product"

        field = self.fields["product_ident"]
        field.choices = tuple(sorted(choices.items()))
        if catalog_unavailable:
            field.help_text = CATALOG_UNAVAILABLE_MESSAGE
            field.disabled = bool(current)


class UserProductGrantInlineFormSet(BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        self.catalog_choices, self.catalog_unavailable = _catalog_choices()
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs.update(
            catalog_choices=self.catalog_choices,
            catalog_unavailable=self.catalog_unavailable,
        )
        return kwargs

    def clean(self):
        if any(self.errors):
            return super().clean()

        seen = set()
        for form in self.forms:
            if form.cleaned_data.get("DELETE"):
                continue
            product_ident = form.cleaned_data.get("product_ident")
            if not product_ident:
                continue
            if product_ident in seen:
                raise forms.ValidationError(
                    "This product is already assigned to the user.",
                )
            seen.add(product_ident)

        return super().clean()


class UserProductGrantInline(admin.TabularInline):
    model = UserProductGrant
    fk_name = "user"
    form = UserProductGrantForm
    formset = UserProductGrantInlineFormSet
    fields = ("product_ident", "created_at", "created_by")
    readonly_fields = ("created_at", "created_by")
    extra = 1
    verbose_name = "Product grant"
    verbose_name_plural = "Product grants — products and QC definitions"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("created_by")
