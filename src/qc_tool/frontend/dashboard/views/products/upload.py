"""Administrator pages for specification uploads and removal."""

from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from qc_tool.common import QCException, current_product_specification_state

from qc_tool.frontend.dashboard.forms.product_specifications import ProductSpecificationForm
from qc_tool.frontend.dashboard.services.catalog.errors import CatalogError
from qc_tool.frontend.dashboard.services.catalog.manifest.definitions import MAX_DEFINITION_BYTES
from qc_tool.frontend.dashboard.services.catalog.specification_upload import (
    add_product_specification, remove_product_specification,
    require_specification_administrator,
)
from qc_tool.frontend.dashboard.models import Product


@transaction.non_atomic_requests
def product_upload(request):
    require_specification_administrator(request.user)
    json_response = "application/json" in request.headers.get("Accept", "").lower()
    form = ProductSpecificationForm(
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None,
    )
    if request.method == "POST" and form.is_valid():
        try:
            result = add_product_specification(form.specification, actor=request.user)
        except CatalogError as exc:
            form.add_error("definition_file", exc.message)
        else:
            if json_response:
                return JsonResponse({
                    "status": "ok",
                    "created": result.created,
                    "product_ident": result.product_ident,
                    "url": reverse("product_detail", args=(result.product_ident,)),
                    "message": "Added to the product catalog." if result.created else "Already added. The same specification is available in the product catalog.",
                })
            messages.success(
                request,
                "Product '{}' is available for quality control. {}".format(
                    result.product_ident,
                    "Its declared product unit scope is ready for review."
                    if result.created else "The same specification was already registered.",
                ),
            )
            return redirect("product_detail", product_ident=result.product_ident)
    if request.method == "POST" and json_response:
        return JsonResponse({
            "status": "error",
            "message": " ".join(
                str(error) for errors in form.errors.values() for error in errors
            ),
        }, status=400)
    return render(request, "dashboard/products/upload.html", {
        "form": form,
        "max_file_bytes": MAX_DEFINITION_BYTES,
    })


@transaction.non_atomic_requests
def product_remove(request, product_ident):
    require_specification_administrator(request.user)
    product = get_object_or_404(Product, ident=product_ident)
    error = None
    if request.method == "POST":
        try:
            remove_product_specification(product_ident, actor=request.user)
        except CatalogError as exc:
            error = exc.message
        else:
            messages.success(request, "Specification '{}' was removed from active use. Its version history is retained.".format(product_ident))
            return redirect("products")
    try:
        state = current_product_specification_state(product_ident)
    except QCException:
        state = None
    removal_pending = not product.is_active and (state is None or state["active"])
    return render(request, "dashboard/products/remove.html", {
        "product": product, "error": error, "removal_pending": removal_pending,
    })
