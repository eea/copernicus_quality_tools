"""Administrator delivery-plan review and activation."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from qc_tool.frontend.dashboard.forms.product_delivery_plan import ProductDeliveryPlanForm
from qc_tool.frontend.dashboard.models import ProductRelease
from qc_tool.frontend.dashboard.services.catalog.delivery_plans import (
    approve_delivery_plan, current_product_manager_ids, manager_assignment_digest,
)
from qc_tool.frontend.dashboard.services.catalog.errors import CatalogError
from qc_tool.frontend.dashboard.services.catalog.specification_upload import require_specification_administrator


def product_plan_edit(request, product_ident, release_id):
    require_specification_administrator(request.user)
    release = get_object_or_404(
        ProductRelease.objects.select_related("product"),
        pk=release_id, product__ident=product_ident,
    )
    assigned_ids = current_product_manager_ids(product_ident)
    form = ProductDeliveryPlanForm(
        request.POST if request.method == "POST" else None,
        initial={
            "expected_release_id": release.pk,
            "expected_manager_digest": manager_assignment_digest(assigned_ids),
            "product_unit_codes": "\n".join(release.product_units.values_list("product_unit_code", flat=True)),
            "product_managers": sorted(assigned_ids),
        },
    )
    if request.method == "POST" and form.is_valid():
        try:
            approved = approve_delivery_plan(
                product_ident, release_id,
                expected_release_id=form.cleaned_data["expected_release_id"],
                expected_manager_digest=form.cleaned_data["expected_manager_digest"],
                product_unit_codes=form.cleaned_data["product_unit_codes"],
                product_managers=form.cleaned_data["product_managers"],
                actor=request.user,
            )
        except CatalogError as exc:
            form.add_error(None, exc.message)
        else:
            messages.success(request, "Delivery plan saved: {} expected product units. Users can submit successful QC deliveries for review.".format(approved.product_units.count()))
            return redirect("product_detail", product_ident=product_ident)
    return render(request, "dashboard/products/plan.html", {
        "product": release.product,
        "release": release,
        "form": form,
        "required_unit_count": release.product_units.count(),
        "manager_count": form.fields["product_managers"].queryset.count(),
    })
