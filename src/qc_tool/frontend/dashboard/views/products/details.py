"""Product detail browser page."""

from django.http import Http404
from django.shortcuts import render

from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard.services.products import build_product_detail


def product_detail(request, product_ident):
    account_access = access_for_request(request)
    can_view_coverage = account_access.can_view_product_report(product_ident)
    product = build_product_detail(
        product_ident,
        include_coverage=can_view_coverage,
    )
    if product is None:
        raise Http404("Product not found.")
    return render(
        request,
        "dashboard/products/detail.html",
        {
            "product": product,
            "can_view_coverage": can_view_coverage,
        },
    )
