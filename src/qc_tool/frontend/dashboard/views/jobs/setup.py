"""Job-setup page and product-form metadata endpoint."""

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.http import HttpResponseBadRequest
from django.http import JsonResponse
from django.shortcuts import render

from qc_tool.common import QCException, compile_job_form_data
from qc_tool.frontend.accounts.services.products import available_product_descriptions
from qc_tool.product_security import normalize_product_ident
from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard import models
from qc_tool.frontend.dashboard.access.deliveries import can_manage_delivery
from qc_tool.frontend.dashboard.services.configuration.presentation import (
    get_announcement_message,
)
from qc_tool.frontend.dashboard.services.requests import IdentifierListError
from qc_tool.frontend.dashboard.services.requests import (
    parse_positive_identifier_list,
)


def setup_job(request):
    """Display the form for starting QC on one or more deliveries."""

    try:
        delivery_ids = parse_positive_identifier_list(
            request.GET.get("deliveries"),
        )
    except IdentifierListError as exc:
        return HttpResponseBadRequest(exc.message)

    account_access = access_for_request(request)
    product_list = _product_options(account_access)
    deliveries_by_id = {
        delivery.id: delivery
        for delivery in models.Delivery.objects.filter(
            id__in=delivery_ids,
            is_deleted=False,
        ).select_related("user")
    }
    if len(deliveries_by_id) != len(delivery_ids):
        raise Http404("One or more selected deliveries do not exist.")

    deliveries = []
    for delivery_id in delivery_ids:
        delivery = deliveries_by_id[delivery_id]
        if delivery.date_submitted is not None:
            raise PermissionDenied(
                "Starting a new QC job on submitted delivery is not permitted."
            )
        if not can_manage_delivery(account_access, delivery):
            raise PermissionDenied(
                "You can run quality checks only on deliveries you manage for assigned products. "
                "Contact an administrator to update your product assignments."
            )
        deliveries.append(delivery)

    product_ident = deliveries[0].product_ident if len(deliveries) == 1 else None
    return render(
        request,
        "dashboard/jobs/setup.html",
        {
            "deliveries": deliveries,
            "product_ident": product_ident,
            "product_list": product_list,
            "show_logo": settings.SHOW_LOGO,
            "announcement": get_announcement_message(),
        },
    )


def get_job_info(request, product_ident):
    """Return the job-step form definition for one product."""

    product_ident = normalize_product_ident(product_ident)
    if (
        product_ident is None
        or product_ident not in available_product_descriptions()
        or not access_for_request(request).can_access_product(product_ident)
    ):
        raise Http404("Product definition not found.")
    try:
        data = compile_job_form_data(product_ident)
    except (KeyError, OSError, QCException, TypeError, UnicodeError, ValueError) as exc:
        raise Http404("Product definition not found.") from exc
    return JsonResponse({"job_result": data})


def _product_options(account_access):
    descriptions = available_product_descriptions()
    options = [
        {
            "product_ident": ident,
            "product_description": description,
        }
        for ident, description in descriptions.items()
        if account_access.can_access_product(ident)
    ]
    return sorted(options, key=lambda item: item["product_description"])
