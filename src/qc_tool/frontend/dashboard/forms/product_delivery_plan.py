"""Explicit review of expected delivery AOIs and product-manager assignments."""

import re

from django import forms

from qc_tool.frontend.dashboard.services.catalog.delivery_plans import (
    delivery_plan_managers, validate_delivery_plan_aois,
)
from qc_tool.frontend.dashboard.services.catalog.errors import CatalogError


class ProductDeliveryPlanForm(forms.Form):
    expected_release_id = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    expected_manager_digest = forms.RegexField(r"\A[0-9a-f]{64}\Z", widget=forms.HiddenInput)
    aoi_codes = forms.CharField(
        label="Expected AOI codes",
        max_length=1024 * 1024,
        help_text="Enter one AOI per line, or separate codes with commas. Equivalent codes count once.",
        widget=forms.Textarea(attrs={"rows": 14, "spellcheck": "false"}),
    )
    product_managers = forms.ModelMultipleChoiceField(
        label="Product managers",
        queryset=None,
        required=False,
        help_text="Selected managers can track this product and approve or decline its submissions. Administrators can always review submissions.",
        widget=forms.CheckboxSelectMultiple,
    )
    confirm_approval = forms.BooleanField(
        label="I confirm that this is the complete delivery plan for this product.",
        error_messages={"required": "Confirm the expected delivery scope before activating the plan."},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product_managers"].queryset = delivery_plan_managers()

    def clean_aoi_codes(self):
        values = [value.strip() for value in re.split(r"[,\r\n]+", self.cleaned_data["aoi_codes"]) if value.strip()]
        try:
            _codes, sources = validate_delivery_plan_aois(values)
        except CatalogError as exc:
            raise forms.ValidationError(exc.message, code=exc.code) from exc
        return list(sources)
