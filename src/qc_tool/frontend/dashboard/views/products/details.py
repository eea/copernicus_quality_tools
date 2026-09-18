"""Product detail browser page with scoped plans and actionable progress."""

from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse

from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard.models import (
    DeliverySubmission, ProductReleaseDefinition, ProductUnit, QcDefinition,
)
from qc_tool.frontend.dashboard.services.catalog.readiness import product_readiness
from qc_tool.frontend.dashboard.services.products import build_product_detail
from qc_tool.frontend.dashboard.services.products.lookup import (
    MAX_CURRENT_RELEASES, product_release_queryset,
)
from qc_tool.frontend.dashboard.services.products.presentation import REMAINING_UNIT_PAGE_SIZE
from qc_tool.frontend.dashboard.services.products.workflows import (
    WORKFLOW_CONFIG, ProductWorkflow, can_show_product_workflow, classify_product_workflow,
)


def product_detail(request, product_ident):
    account_access = access_for_request(request)
    if not account_access.can_browse_product(product_ident):
        raise PermissionDenied("This product is not assigned to your account.")
    can_view_coverage = account_access.can_view_product_report(product_ident)
    complete_scope = (
        account_access.is_administrator
        or product_ident in account_access.reportable_product_idents
    )
    delivery_plans = product_release_queryset(
        product_ident,
        definition_idents=None if complete_scope else account_access.product_idents,
    )
    release_page = Paginator(delivery_plans, MAX_CURRENT_RELEASES).get_page(
        request.GET.get("releases_page"),
    )
    releases = tuple(release_page)
    product = build_product_detail(
        product_ident, include_coverage=can_view_coverage,
        releases=releases, releases_truncated=release_page.has_other_pages(),
    )
    if product is None:
        raise Http404("Product not found.")
    catalog_product = releases[0].product
    product_is_active = catalog_product.is_active
    readiness = product_readiness(catalog_product) if complete_scope else None
    plan_states = tuple(delivery_plans.values_list("coverage_state", flat=True))
    workflow = classify_product_workflow(
        is_active=product_is_active, coverage_states=plan_states,
        is_ready=bool(readiness and readiness.is_ready),
    )
    navigation_workflow = workflow
    if not can_show_product_workflow(
        workflow, account_access=account_access,
        has_completed_products=bool(readiness and readiness.is_ready),
    ):
        navigation_workflow = ProductWorkflow.ACTIVE
    current_digests = set(ProductReleaseDefinition.objects.filter(
        product_release__in=delivery_plans,
    ).values_list("qc_definition__digest", flat=True)) if product_is_active else set()
    versions = QcDefinition.objects.filter(product_ident=product_ident).only(
        "product_ident", "digest", "imported_at"
    ).order_by("-imported_at", "-pk")
    # A recipe grant authorizes that recipe's stored versions, not a separate
    # parent definition merely because it shares the browsable catalog page.
    if not account_access.can_access_product_snapshot(product_ident):
        versions = versions.none()
    version_page = Paginator(versions, 20).get_page(request.GET.get("versions_page"))
    specification_versions = tuple({
        "ident": version.product_ident,
        "digest": version.digest,
        "imported_at": version.imported_at,
        "is_current": version.digest in current_digests,
    } for version in version_page)
    visible_readiness = readiness if can_view_coverage else None
    detail_plans = tuple(
        _plan_context(request, release, detail, account_access, can_view_coverage)
        for release, detail in zip(releases, product.releases)
    )
    return render(request, "dashboard/products/detail.html", {
        "product": product,
        "can_view_coverage": can_view_coverage,
        "product_is_active": product_is_active,
        "readiness": visible_readiness,
        "product_catalog_url": "{}?product_view={}".format(
            reverse("products"), navigation_workflow.value,
        ),
        "product_workflow_label": WORKFLOW_CONFIG[navigation_workflow.value]["label"],
        "product_workflow": workflow.value,
        "product_lifecycle_label": WORKFLOW_CONFIG[workflow.value]["label"],
        "specification_versions": specification_versions,
        "specification_version_page": version_page,
        "previous_versions_url": _page_url(
            request, version_page, "versions_page", "specification-history", previous=True,
        ),
        "next_versions_url": _page_url(
            request, version_page, "versions_page", "specification-history",
        ),
        "can_review_submissions": account_access.can_review_product_submission(product_ident),
        "delivery_plans": delivery_plans,
        "detail_plans": detail_plans,
        "release_page": release_page,
        "release_count": release_page.paginator.count,
        "previous_releases_url": _page_url(
            request, release_page, "releases_page", "delivery-plans-title", previous=True,
        ),
        "next_releases_url": _page_url(
            request, release_page, "releases_page", "delivery-plans-title",
        ),
        "overview": _overview(
            product, workflow, visible_readiness, delivery_plans,
            account_access=account_access, plan_states=plan_states,
        ),
    })


def _page_url(request, page, parameter, anchor, *, previous=False):
    if not (page.has_previous() if previous else page.has_next()):
        return ""
    parameters = request.GET.copy()
    parameters[parameter] = page.previous_page_number() if previous else page.next_page_number()
    return "?{}#{}".format(parameters.urlencode(), anchor)


def _unit_scope_url(request, parameter, scope, scope_parameter, release_id):
    parameters = request.GET.copy()
    parameters.pop(parameter, None)
    parameters[scope_parameter] = scope
    return "?{}#product-units-{}".format(parameters.urlencode(), release_id)


def _plan_context(request, release, detail, account_access, can_view_coverage):
    parameter = "units_page_{}".format(release.pk)
    scope_parameter = "unit_scope_{}".format(release.pk)
    authoritative = release.coverage_state == "authoritative"
    remaining = detail.coverage.remaining if detail.coverage else None
    scope = request.GET.get(scope_parameter)
    all_units = scope == "all" or (scope != "remaining" and remaining == 0)
    units_kind = "remaining" if authoritative and not all_units else "required"
    units_page = None
    if can_view_coverage:
        units = ProductUnit.objects.filter(product_release=release)
        if units_kind == "remaining":
            accepted = DeliverySubmission.objects.filter(
                product_unit_id=OuterRef("pk"), product_release=release,
                publication_state=DeliverySubmission.PublicationState.PUBLISHED,
                review_state=DeliverySubmission.ReviewState.ACCEPTED,
            )
            units = units.annotate(has_accepted_delivery=Exists(accepted)).filter(
                has_accepted_delivery=False,
            )
        units = units.order_by("product_unit_code").values_list("product_unit_code", flat=True)
        units_page = Paginator(units, REMAINING_UNIT_PAGE_SIZE).get_page(request.GET.get(parameter))
    return {
        "detail": detail, "id": release.pk,
        "label": release.description or release.release_key,
        "status_label": {
            "authoritative": "Approved", "draft": "Draft",
            "unknown": "Not defined", "retired": "Retired",
        }.get(release.coverage_state, "Not defined"),
        "edit_url": reverse("product_plan_edit", args=(release.product.ident, release.pk))
        if account_access.can_manage_product_catalog and release.product.is_active else "",
        "units_page": units_page, "units_kind": units_kind,
        "units_page_param": parameter,
        "units_expanded": parameter in request.GET or scope_parameter in request.GET,
        "previous_units_url": _page_url(
            request, units_page, parameter, "product-units-{}".format(release.pk), previous=True,
        ) if units_page is not None else "",
        "next_units_url": _page_url(
            request, units_page, parameter, "product-units-{}".format(release.pk),
        ) if units_page is not None else "",
        "all_units_url": _unit_scope_url(request, parameter, "all", scope_parameter, release.pk)
        if can_view_coverage and authoritative else "",
        "remaining_units_url": _unit_scope_url(request, parameter, "remaining", scope_parameter, release.pk)
        if can_view_coverage and authoritative else "",
    }


def _overview(product, workflow, readiness, delivery_plans, *, account_access, plan_states):
    """Choose the next permitted action from the product's actual lifecycle."""

    can_review = account_access.can_review_product_submission(product.ident)
    can_finalize = bool(readiness and readiness.can_finalize and can_review)
    approved_scope = bool(plan_states) and set(plan_states) == {"authoritative"}
    required = readiness.required_units if readiness else None
    show_progress = bool(readiness and approved_scope)
    overview = {
        "title": readiness.label if readiness else WORKFLOW_CONFIG[workflow.value]["label"],
        "message": readiness.message if readiness else "",
        "action_label": "", "action_url": "", "can_finalize": can_finalize,
        "show_progress": show_progress, "required": required,
        "accepted": readiness.accepted_units if show_progress else None,
        "remaining": max(required - readiness.accepted_units, 0) if show_progress else None,
        "percentage": round(100 * readiness.accepted_units / required, 2)
        if show_progress and required else 0 if show_progress else None,
    }
    if workflow == ProductWorkflow.STOPPED:
        overview.update(
            title="Product stopped",
            message="New quality-control jobs are unavailable. Product specifications and delivery history remain available.",
        )
        if account_access.can_manage_product_catalog:
            overview.update(action_label="Restore product", action_url=reverse("product_upload"))
    elif workflow == ProductWorkflow.DRAFT:
        overview.update(
            title="Delivery plan approval required",
            message="An administrator must review the required product units and approve every delivery plan before deliveries can be submitted for review.",
        )
        if account_access.can_manage_product_catalog:
            single_plan = delivery_plans.first() if delivery_plans.count() == 1 else None
            overview.update(
                action_label="Set up delivery plan" if single_plan else "Review delivery plans",
                action_url=reverse("product_plan_edit", args=(product.ident, single_plan.pk))
                if single_plan else "#delivery-plans-title",
            )
    elif workflow == ProductWorkflow.COMPLETED:
        overview.update(
            title="Product completed",
            message="All required product units have accepted deliveries and a product manager has confirmed the product is ready.",
        )
    elif can_finalize:
        overview.update(action_label="Mark product ready")
    elif can_review:
        overview.update(
            action_label="Review submissions",
            action_url="{}?{}".format(reverse("submission_queue"), urlencode({"product": product.ident})),
        )
    elif account_access.can_upload and (
        account_access.can_access_product(product.ident)
        or any(
            account_access.can_access_product(definition.ident)
            for detail in product.releases for definition in detail.definitions
        )
    ):
        overview.update(
            action_label="Upload a delivery", action_url=reverse("file_upload"),
        )
        if not readiness:
            overview["message"] = "Upload a delivery, run its QC checks, then submit it for review from Deliveries."
    elif not readiness:
        overview["message"] = "The delivery plan is approved. View the product specification and delivery plan below."
    return overview
