"""Bounded product specification upload validation."""

from django import forms

from qc_tool.frontend.dashboard.services.catalog.errors import CatalogError
from qc_tool.frontend.dashboard.services.catalog.specification_upload import (
    read_specification_upload,
)


class ProductSpecificationForm(forms.Form):
    definition_file = forms.FileField(
        label="Product specification JSON",
        widget=forms.FileInput(attrs={
            "accept": ".json,application/json",
            "aria-describedby": "product-upload-hint product-upload-error",
        }),
    )

    def clean_definition_file(self):
        if len(self.files.getlist("definition_file")) != 1:
            raise forms.ValidationError("Choose one JSON specification at a time.")
        uploaded = self.cleaned_data["definition_file"]
        try:
            self.specification = read_specification_upload(uploaded)
        except CatalogError as exc:
            raise forms.ValidationError(exc.message, code=exc.code) from exc
        return uploaded
