"""Authenticated product data endpoints used by browser clients."""

import re

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
    """Return a selected stored revision, or the current executable file."""

    product_ident = normalize_product_ident(product_ident)
    if product_ident is None:
        raise Http404("Product definition not found.")
    if "digest" in request.GET:
        return _stored_definition(product_ident, request.GET.getlist("digest"))
    try:
        filepath = locate_product_definition(product_ident)
        return FileResponse(
            open(str(filepath), "rb"),
            content_type="application/json",
        )
    except (FileNotFoundError, OSError, QCException) as error:
        raise Http404("Product definition not found.") from error


def _stored_definition(product_ident, digests):
    # An explicit revision must never fall back to a newer executable file.
    if len(digests) != 1 or re.fullmatch(r"[0-9a-f]{64}", digests[0]) is None:
        raise Http404("Product definition revision not found.")
    try:
        definition = models.QcDefinition.objects.only("document").get(
            product_ident=product_ident,
            digest=digests[0],
        )
    except models.QcDefinition.DoesNotExist as error:
        raise Http404("Product definition revision not found.") from error
    return JsonResponse(definition.document, json_dumps_params={"indent": 2})
