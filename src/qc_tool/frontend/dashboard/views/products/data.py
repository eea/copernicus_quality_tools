"""Authenticated product data endpoints used by browser clients."""

from django.http import FileResponse
from django.http import Http404
from django.http import JsonResponse

import qc_tool.frontend.dashboard.models as models
from qc_tool.common import get_product_descriptions
from qc_tool.common import locate_product_definition
from qc_tool.common import QCException
from qc_tool.product_security import normalize_product_ident


def get_product_list(request):
    product_infos = get_product_descriptions()
    product_list = sorted(
        (
            {"name": product_ident, "description": description}
            for product_ident, description in product_infos.items()
        ),
        key=lambda item: item["description"],
    )
    return JsonResponse({"product_list": product_list})


def get_product_descriptions_dropdown(request):
    descriptions = (
        models.Delivery.objects.filter(is_deleted=False, user=request.user)
        .values_list("product_description", flat=True)
        .distinct()
        .order_by("product_description")
    )
    return JsonResponse({description: description for description in descriptions})


def get_product_definition(request, product_ident):
    """Return the executable definition through its explicit data route."""

    product_ident = normalize_product_ident(product_ident)
    if product_ident is None:
        raise Http404("Product definition not found.")
    try:
        filepath = locate_product_definition(product_ident)
        return FileResponse(
            open(str(filepath), "rb"),
            content_type="application/json",
        )
    except (FileNotFoundError, OSError, QCException) as error:
        raise Http404("Product definition not found.") from error
