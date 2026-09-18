"""Product detail browser page."""

from django.http import Http404
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import render
from django.urls import reverse

from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard.services.products import build_product_detail
from qc_tool.frontend.dashboard.models import Product, QcDefinition, ProductReleaseDefinition, ProductRelease
from qc_tool.frontend.dashboard.services.catalog.readiness import product_readiness
from qc_tool.frontend.dashboard.services.products.workflows import (
    WORKFLOW_CONFIG, ProductWorkflow, can_show_product_workflow, classify_product_workflow,
)


def product_detail(request, product_ident):
    account_access = access_for_request(request)
    if not account_access.can_browse_product(product_ident):
        raise PermissionDenied("This product is not assigned to your account.")
    can_view_coverage = account_access.can_view_product_report(product_ident)
    product = build_product_detail(
        product_ident,
        include_coverage=can_view_coverage,
    )
    if product is None:
        raise Http404("Product not found.")
    catalog_product = Product.objects.filter(ident=product_ident).first()
    product_is_active = catalog_product.is_active if catalog_product else True
    delivery_plans = ProductRelease.objects.filter(
        product__ident=product_ident, is_current=True,
    ).order_by("release_key")
    complete_scope = account_access.is_administrator or product_ident in account_access.reportable_product_idents
    readiness = product_readiness(catalog_product) if catalog_product and complete_scope else None
    workflow_plans = delivery_plans if complete_scope else delivery_plans.filter(
        definition_links__qc_definition__product_ident__in=account_access.product_idents,
    )
    workflow = classify_product_workflow(
        is_active=product_is_active,
        coverage_states=workflow_plans.values_list("coverage_state", flat=True),
        is_ready=bool(readiness and readiness.is_ready),
    )
    if not can_show_product_workflow(
        workflow, account_access=account_access,
        has_completed_products=bool(readiness and readiness.is_ready),
    ):
        workflow = ProductWorkflow.ACTIVE
    current_digests = set(ProductReleaseDefinition.objects.filter(
        product_release__product__ident=product_ident,
        product_release__is_current=True,
    ).values_list("qc_definition__digest", flat=True)) if product_is_active else set()
    versions = QcDefinition.objects.filter(product_ident=product_ident).only(
        "product_ident", "digest", "imported_at"
    ).order_by("-imported_at", "-pk")
    version_page = Paginator(versions, 20).get_page(request.GET.get("versions_page"))
    specification_versions = tuple({
        "ident": version.product_ident,
        "digest": version.digest,
        "imported_at": version.imported_at,
        "is_current": version.digest in current_digests,
    } for version in version_page)
    return render(
        request,
        "dashboard/products/detail.html",
        {
            "product": product,
            "can_view_coverage": can_view_coverage,
            "product_is_active": product_is_active,
            "readiness": readiness if can_view_coverage else None,
            "product_catalog_url": "{}?product_view={}".format(reverse("products"), workflow.value),
            "product_workflow_label": WORKFLOW_CONFIG[workflow.value]["label"],
            "specification_versions": specification_versions,
            "specification_version_page": version_page,
            "can_review_submissions": account_access.can_review_product_submission(product_ident),
            "delivery_plans": delivery_plans,
        },
    )
