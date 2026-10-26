"""Reusable, explicit catalog selection for additive product assignments."""

import json
from collections import Counter

from django import forms


class AssignedProductDisplay(forms.Widget):
    """Show an existing grant without repeating the full catalog in each row."""

    template_name = "accounts/widgets/assigned_product.html"

    def __init__(self, *, label, **kwargs):
        self.label = label
        super().__init__(**kwargs)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["display_label"] = self.label
        return context


class BulkProductSelect(forms.CheckboxSelectMultiple):
    """Keep a large checkbox selection in one bounded, server-validated field."""

    template_name = "accounts/widgets/bulk_product_select.html"
    option_template_name = "accounts/widgets/bulk_product_option.html"

    class Media:
        css = {"all": ("accounts/css/admin/bulk-product-select.css",)}
        js = (
            "dashboard/js/shared/checkbox-selection.js",
            "accounts/js/admin/bulk-product-select.js",
        )

    def __init__(self, *args, assigned_idents=(), **kwargs):
        self.assigned_idents = frozenset(assigned_idents)
        super().__init__(*args, **kwargs)

    def create_option(self, name, value, label, selected, index, **kwargs):
        option = super().create_option(name, value, label, selected, index, **kwargs)
        if value in self.assigned_idents:
            option["attrs"].update(disabled=True, checked=True, **{"data-already-assigned": "true"})
        return option

    def value_from_datadict(self, data, files, name):
        raw = data.get(name, "")
        if not raw:
            return []
        # Every canonical identifier is at most 64 characters. This bound also
        # prevents an invented, very large JSON field from bypassing form limits.
        if not isinstance(raw, str) or len(raw) > len(self.choices) * 80 + 2:
            return "invalid-selection"
        try:
            values = json.loads(raw)
        except (TypeError, ValueError):
            return "invalid-selection"
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            return "invalid-selection"
        return values

    def get_context(self, name, value, attrs):
        if not isinstance(value, (list, tuple)):
            value = []
        context = super().get_context(name, value, attrs)
        widget = context["widget"]
        selected = [ident for ident in value or () if ident not in self.assigned_idents]
        widget["selection_json"] = json.dumps(selected)
        widget["selected_count"] = len(selected)
        widget["assigned_count"] = len(self.assigned_idents.intersection(dict(self.choices)))
        families = Counter()
        for ident, _label in self.choices:
            parts = ident.split("_")
            if len(parts) > 1:
                families["_".join(parts[:2] if len(parts) > 2 else parts[:1])] += 1
        widget["families"] = [
            {"prefix": prefix, "count": count}
            for prefix, count in sorted(families.items()) if count > 1
        ]
        return context


class BulkProductAssignmentForm(forms.Form):
    products = forms.MultipleChoiceField(
        required=False, choices=(), widget=BulkProductSelect,
        error_messages={"invalid_list": "Select existing specifications from the list."},
    )

    def __init__(self, *args, catalog_choices=(), assigned_idents=(),
                 assignment_allowed=True, catalog_unavailable=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.assignment_allowed = assignment_allowed
        self.catalog_unavailable = catalog_unavailable
        field = self.fields["products"]
        field.choices = catalog_choices
        field.widget.assigned_idents = frozenset(assigned_idents)

    def clean_products(self):
        products = tuple(self.cleaned_data["products"])
        if len(products) != len(set(products)):
            raise forms.ValidationError("Select each specification once.")
        if products and not self.assignment_allowed:
            raise forms.ValidationError("You cannot add product assignments.")
        if products and self.catalog_unavailable:
            raise forms.ValidationError("The product catalog is unavailable. Reload before adding assignments.")
        return products
