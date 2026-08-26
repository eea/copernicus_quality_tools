"""Product catalog pages and browser data endpoints."""

import logging
from django.http import FileResponse
from django.http import Http404
from django.http import JsonResponse
from django.shortcuts import render
import qc_tool.frontend.dashboard.models as models
from qc_tool.frontend.accounts.services.products import (
    ProductCatalogUnavailable,
)
from qc_tool.frontend.accounts.services.products import (
    available_product_descriptions,
)
from qc_tool.common import get_product_descriptions
from qc_tool.common import locate_product_definition

logger = logging.getLogger(__name__)


def products(request):
    """List the complete product catalog without exposing definition files."""

    product_catalog, product_catalog_available = _workspace_product_catalog()
    return render(
        request,
        "dashboard/products/index.html",
        {
            "product_catalog": product_catalog,
            "product_catalog_available": product_catalog_available,
        },
    )


def _workspace_product_catalog():
    """Return safe display records while keeping catalog failures non-fatal."""

    try:
        descriptions = available_product_descriptions()
    except ProductCatalogUnavailable:
        logger.warning("The product catalog is unavailable for the workspace UI.")
        return (), False

    return (
        tuple(
            {
                "ident": product_ident,
                "description": description,
            }
            for product_ident, description in sorted(
                descriptions.items(),
                key=lambda item: (str(item[1]).casefold(), item[0]),
            )
        ),
        True,
    )


def get_product_list(request):
    """
    returns a list of all product types that are available for checking.
    :param request:
    :return: list of the product types with items {name, description} in JSON format
    """
    product_infos = get_product_descriptions()
    product_list = [{'name': product_ident, 'description': product_description}
                    for product_ident, product_description in product_infos.items()]
    product_list = sorted(product_list, key=lambda x: x['description'])
    return JsonResponse({'product_list': product_list})


def get_product_descriptions_dropdown(request):
    """
    returns a list of product descriptions for the UI filter dropdown based on current user.
    :param request:
    :return: dictionary of the product descriptions
    """
    product_descriptions = sorted(
        models.Delivery.objects.filter(
            is_deleted=False,
            user=request.user,
        )
        .values_list("product_description", flat=True)
        .distinct()
    )
    product_dict = {}
    for item in product_descriptions:
        product_dict[item] = item
    return JsonResponse(product_dict)


def get_product_definition(request, product_ident):
    """
    Shows the json product definition.
    """
    filepath = locate_product_definition(product_ident)
    try:
        return FileResponse(open(str(filepath), "rb"), content_type="application/json")
    except FileNotFoundError:
        raise Http404()
