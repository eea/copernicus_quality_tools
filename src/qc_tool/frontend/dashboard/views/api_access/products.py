"""API product discovery endpoints."""

from django.http import JsonResponse
from qc_tool.common import QCException
from qc_tool.common import compile_job_form_data
from qc_tool.common import get_product_descriptions
from qc_tool.product_security import normalize_product_ident


def api_product_list(request):
    product_infos = get_product_descriptions()
    product_list = [
        {
            "product_ident": product_ident,
            "description": product_description,
        }
        for product_ident, product_description in product_infos.items()
    ]
    product_list = sorted(product_list, key=lambda x: x["product_ident"])
    return JsonResponse({"products": product_list})


def api_product_info(request, product_ident):
    """
    returns a table of details about the product
    :param request:
    :param product_ident: the name of the product type for example clc
    :return: product details with a list of job steps and their type (system, required, optional)
    """
    try:
        product_ident = normalize_product_ident(product_ident)
        if product_ident is None:
            raise QCException("Product identifier is not canonical.")
        job_form_data = compile_job_form_data(product_ident)
    except (KeyError, OSError, QCException, TypeError, UnicodeError, ValueError):
        return JsonResponse(
            {
                "status": "error",
                "code": "product_not_found",
                "message": "The requested product is unavailable.",
            },
            status=404,
        )
    response_data = {
        "status": "ok",
        "message": f"showing available checks for {product_ident}",
        "data": job_form_data,
    }
    return JsonResponse(response_data, safe=False)
