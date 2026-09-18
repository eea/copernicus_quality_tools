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
from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard.access.delivery_querysets import visible_deliveries


def get_product_list(request):
    access = access_for_request(request)
    product_infos = get_product_descriptions()
    product_list = sorted(
        (
            {"name": product_ident, "description": description}
            for product_ident, description in product_infos.items()
            if access.can_access_product(product_ident)
        ),
        key=lambda item: item["description"],
    )
    return JsonResponse({"product_list": product_list})


def get_product_descriptions_dropdown(request):
    descriptions = (
        visible_deliveries(access_for_request(request)).filter(is_deleted=False, user=request.user)
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
    access = access_for_request(request)
    if "digest" in request.GET:
        return _stored_definition(product_ident, request.GET.getlist("digest"), access)
    if not access.can_access_product(product_ident):
        raise Http404("Product definition not found.")
    try:
        filepath = locate_product_definition(product_ident)
        return FileResponse(
            open(str(filepath), "rb"),
            content_type="application/json",
        )
    except (FileNotFoundError, OSError, QCException) as error:
        raise Http404("Product definition not found.") from error


def _stored_definition(product_ident, digests, account_access):
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
    if not account_access.can_access_product_snapshot(product_ident):
        parent_idents = definition.release_links.values_list(
            "product_release__product__ident", flat=True,
        )
        if not any(
            account_access.can_access_product_snapshot(product_ident, parent_ident)
            for parent_ident in parent_idents
        ):
            raise Http404("Product definition revision not found.")
    return JsonResponse(definition.document, json_dumps_params={"indent": 2})
