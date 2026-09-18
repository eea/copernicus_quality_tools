"""Final manager confirmation of a product's accepted required units."""

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect

from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard.models import Product
from qc_tool.frontend.dashboard.services.catalog.readiness import finalize_product, ProductReadinessError


def product_finalize(request, product_ident):
    try:
        finalize_product(
            product_ident=product_ident,
            actor=request.user,
            account_access=access_for_request(request),
            expected_scope_digest=request.POST.get("expected_scope_digest"),
        )
    except Product.DoesNotExist as exc:
        raise Http404("Product not found.") from exc
    except ProductReadinessError as exc:
        from .details import product_detail

        messages.error(request, exc.message)
        response = product_detail(request, product_ident)
        response.status_code = 409
        return response
    messages.success(request, "Product confirmed ready.")
    return redirect("product_detail", product_ident=product_ident)
