"""Job-setup page and product-form metadata endpoint."""

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.http import HttpResponseBadRequest
from django.http import JsonResponse
from django.shortcuts import render

from qc_tool.common import QCException, compile_job_form_data
from qc_tool.delivery_names import DeliveryNameParserUnavailable
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
from qc_tool.frontend.dashboard.services.products.identification import (
    identification_preview, identify_delivery,
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

    response_status = 200
    try:
        identification_context = _filename_options(deliveries, product_list, account_access)
    except DeliveryNameParserUnavailable:
        response_status = 503
        identification_context = {
            "product_list": [], "product_ident": None,
            "delivery_identifications": tuple({"delivery": delivery} for delivery in deliveries),
            "has_filename_hints": False, "identification_blocks_jobs": True,
            "identification_notice": "Delivery filename recognition is temporarily unavailable. Try again later.",
        }
    return render(
        request,
        "dashboard/jobs/setup.html",
        {
            "deliveries": deliveries,
            **identification_context,
            "show_logo": settings.SHOW_LOGO,
            "announcement": get_announcement_message(),
        },
        status=response_status,
    )


def _filename_options(deliveries, product_list, account_access):
    """Show filename hints without treating them as verified delivery metadata."""

    results = tuple(identify_delivery(delivery.filename) for delivery in deliveries)
    previews = tuple({
        "delivery": delivery,
        "identification": identification_preview(result, account_access),
    } for delivery, result in zip(deliveries, results))
    recognized = tuple(result for result in results if result.status in {"matched", "ambiguous"})
    blocked = any(result.status in {"invalid", "unconfigured"} for result in results)
    candidates = None
    for result in recognized:
        candidates = set(result.candidates) if candidates is None else candidates.intersection(result.candidates)
    notice = ""
    if blocked:
        product_list = []
        notice = "A delivery filename needs attention before QC can run. Review its filename details and try again."
    elif candidates is not None:
        product_list = [option for option in product_list if option["product_ident"] in candidates]
        if not candidates:
            blocked = True
            notice = "The selected deliveries do not share a product specification. Start separate QC jobs for these products."
        elif not product_list:
            blocked = True
            notice = "No assigned product matches the selected delivery filenames. Contact an administrator to update your product assignments."
        elif any(result.status == "ambiguous" for result in recognized):
            notice = "A filename matches more than one product specification. Choose the correct specification for these deliveries."
    available = {option["product_ident"] for option in product_list}
    product_ident = None
    if recognized and all(result.status == "matched" for result in recognized) and len(available) == 1:
        product_ident = next(iter(available))
    elif not recognized and len(deliveries) == 1 and deliveries[0].product_ident in available:
        product_ident = deliveries[0].product_ident
    return {
        "product_list": product_list, "product_ident": product_ident,
        "delivery_identifications": previews,
        "has_filename_hints": any(result.parsed.status == "recognized" for result in results),
        "identification_blocks_jobs": blocked,
        "identification_notice": notice,
    }


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
