"""Delivery submission receipts and the assigned-manager review workspace."""

from pathlib import PurePosixPath
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard.forms.submission_reviews import SubmissionReviewForm
from qc_tool.frontend.dashboard.forms.submission_bulk_review import (
    BulkSubmissionReviewForm, submission_selection_token,
)
from qc_tool.frontend.dashboard.models import SubmissionConflict
from qc_tool.frontend.dashboard.services.artifacts import ArtifactUnavailable
from qc_tool.frontend.dashboard.services.deliveries.listing.statuses import classify_delivery_status
from qc_tool.frontend.dashboard.services.deliveries.listing.workflows import classify_delivery_workflow
from qc_tool.frontend.dashboard.services.submissions import SubmissionError, resolve_submission_conflict
from qc_tool.frontend.dashboard.services.submissions.access import (
    awaiting_review_submissions,
    reviewable_submissions,
    visible_submissions,
)
from qc_tool.frontend.dashboard.services.submissions.artifacts import submission_inventory, open_submission_file
from qc_tool.frontend.dashboard.services.submissions.detail_presentation import submission_detail_presentation
from qc_tool.frontend.dashboard.services.submissions.bulk_review import (
    MAX_BULK_APPROVALS, annotate_bulk_approval_eligibility,
    bulk_approval_block_reason, bulk_approve_submissions,
)
from qc_tool.frontend.dashboard.services.submissions.presentation import correction_context, current_review_feedback
from qc_tool.frontend.dashboard.services.submissions.review import review_submission


def submission_queue(request):
    access = access_for_request(request)
    if not access.can_view_submission_queue:
        return redirect(_deliveries_workflow_url("in_review"))
    state = request.GET.get("state", "pending")
    if state not in {"pending", "accepted", "rejected", "all"}:
        state = "pending"
    if state == "pending":
        queryset = awaiting_review_submissions(access)
    else:
        queryset = reviewable_submissions(access)
        if state != "all":
            queryset = queryset.filter(review_state=state)
    product = request.GET.get("product", "")
    if product:
        queryset = queryset.filter(product_release__product__ident=product)
    delivery = request.GET.get("delivery", "")
    if delivery:
        queryset = queryset.filter(delivery_id=int(delivery)) if delivery.isdecimal() and len(delivery) < 19 else queryset.none()
    selected_product_name = ""
    if product:
        selected_product_name = reviewable_submissions(access).filter(
            product_release__product__ident=product,
        ).values_list("product_release__product__name", flat=True).first() or ""
    page = Paginator(
        annotate_bulk_approval_eligibility(queryset).order_by("requested_at", "pk"),
        MAX_BULK_APPROVALS,
    ).get_page(request.GET.get("page"))
    eligible_count = 0
    for item in page:
        item.bulk_block_reason = bulk_approval_block_reason(item)
        item.bulk_selection = ""
        if not item.bulk_block_reason:
            item.bulk_selection = submission_selection_token(item, request.user.pk)
            eligible_count += 1
    return render(request, "dashboard/submissions/index.html", {
        "review_items": page, "selected_state": state, "selected_product": product,
        "selected_delivery": delivery, "selected_product_name": selected_product_name,
        "bulk_action_url": _submission_queue_url(request.GET, route="submission_bulk_approve"),
        "bulk_eligible_count": eligible_count,
        "can_review": True,
    })


def _submission_queue_url(query, *, route="submission_queue"):
    filters = {key: query[key] for key in ("state", "product", "delivery", "page") if query.get(key)}
    return reverse(route) + ("?" + urlencode(filters) if filters else "")


def submission_bulk_approve(request):
    access = access_for_request(request)
    if not access.can_view_submission_queue:
        raise PermissionDenied("Only assigned product managers and administrators can approve submissions.")
    form = BulkSubmissionReviewForm(request.POST, reviewer_id=request.user.pk)
    items = []
    ready = False
    status = 200
    valid = form.is_valid()
    if "selection" in form.cleaned_data and "intent" in form.cleaned_data:
        ids = [ident for ident, _version in form.selections]
        items = list(annotate_bulk_approval_eligibility(reviewable_submissions(access)).filter(
            pk__in=ids,
        ).order_by("requested_at", "pk"))
        versions = dict(form.selections)
        if len(items) != len(ids):
            items = []
            form.add_error(None, "One or more selected submissions are no longer available for you to review.")
            status = 403
        else:
            for item in items:
                item.bulk_block_reason = bulk_approval_block_reason(item)
                if item.review_version != versions[item.pk]:
                    item.bulk_block_reason = "The review changed. Return to the list and select the deliveries again."
            ready = not any(item.bulk_block_reason for item in items)
            if not ready:
                form.add_error(None, "No deliveries were approved. Check the issues below, then return to the submission list.")
                status = 409
            elif valid and form.cleaned_data["intent"] == "approve":
                try:
                    count = bulk_approve_submissions(
                        selections=form.selections, actor=request.user,
                        account_access=access, notes=form.cleaned_data["notes"],
                    )
                except SubmissionError as exc:
                    form.add_error(None, "No deliveries were approved. " + exc.message)
                    ready = False
                    status = exc.status_code
                else:
                    messages.success(request, "{} submission{} approved.".format(count, "" if count == 1 else "s"))
                    return redirect(_submission_queue_url(request.GET))
    if not valid:
        status = 400
    return render(request, "dashboard/submissions/bulk_approve.html", {
        "form": form, "selected_items": items, "selection_ready": ready,
        "submission_workspace_url": _submission_queue_url(request.GET),
    }, status=status)


def _deliveries_workflow_url(workflow):
    return "{}?delivery_view={}".format(reverse("deliveries"), workflow)


def _submission_workspace_navigation(access, submission):
    if access.can_view_submission_queue:
        return {
            "submission_section_url": reverse("products"),
            "submission_section_label": "Products",
            "submission_workspace_url": reverse("submission_queue"),
            "submission_workspace_label": "Submission review",
            "submission_return_label": "Back to submission review",
            "submission_breadcrumb_label": "Review",
        }
    status = classify_delivery_status(
        submission.job.job_status, submission.delivery.date_submitted,
        submission.review_state, submission.publication_state,
    )
    return {
        "submission_workspace_url": _deliveries_workflow_url(classify_delivery_workflow(status)),
        "submission_workspace_label": "Deliveries",
        "submission_return_label": "Back to deliveries",
        "submission_breadcrumb_label": "Submission",
    }


def submission_review(request, submission_id):
    access = access_for_request(request)
    submission = get_object_or_404(visible_submissions(access), pk=submission_id)
    can_review = access.can_review_product_submission(submission.product_release.product.ident)
    conflict = SubmissionConflict.objects.filter(product_unit=submission.product_unit).first()
    form = SubmissionReviewForm(
        request.POST if request.method == "POST" else None,
        initial={
            "expected_review_version": submission.review_version,
            "expected_conflict_version": conflict.version if conflict else None,
        },
    )
    if request.method == "POST":
        if not can_review:
            raise PermissionDenied("Only assigned product managers and administrators can review submissions.")
        if form.is_valid():
            try:
                if form.cleaned_data["decision"] == "replace":
                    if not conflict or submission.review_version != form.cleaned_data["expected_review_version"]:
                        raise SubmissionError("submission_changed", "The review changed. Refresh and try again.", 409)
                    resolve_submission_conflict(
                        conflict_id=conflict.pk, selected_submission_id=submission.pk,
                        actor=request.user, account_access=access,
                        expected_version=form.cleaned_data["expected_conflict_version"],
                        notes=form.cleaned_data["notes"],
                    )
                else:
                    review_submission(
                        submission_id=submission.pk, decision=form.cleaned_data["decision"],
                        actor=request.user, account_access=access,
                        expected_review_version=form.cleaned_data["expected_review_version"],
                        notes=form.cleaned_data["notes"],
                    )
            except SubmissionError as exc:
                form.add_error(None, exc.message)
            else:
                messages.success(request, (
                    "Submission rejected. Your feedback is now visible to the uploader."
                    if form.cleaned_data["decision"] == "declined"
                    else "Submission approved."
                ))
                return redirect("submission_review", submission_id=submission.pk)
    files = []
    storage_available = False
    try:
        _root, inventory = submission_inventory(submission)
        files = [{"name": path, "size": value[1], "url": reverse(
            "submission_file", kwargs={"submission_id": submission.pk, "filename": path},
        )} for path, value in sorted(inventory.items())]
        storage_available = True
    except (ArtifactUnavailable, OSError):
        pass
    events = list(submission.review_events.select_related("actor").order_by("created_at", "pk"))
    detail = submission_detail_presentation(
        submission, can_review=can_review, storage_available=storage_available,
        files=files, conflict=conflict,
    )
    summary = {
        "kind": "Submitted delivery", "icon": "file",
        "reference": "#{}".format(submission.delivery_id),
        "title": submission.delivery.filename,
        "description_label": "Product",
        "description": submission.product_release.product.name,
        "description_url": reverse("product_detail", args=(submission.product_release.product.ident,)),
        "status_label": "Review status", "status": detail["status"],
        "status_description": detail["status"]["message"],
        "facts": [
            {"label": "Product unit", "value": submission.product_unit_code},
            {"label": "Submitted by", "value": submission.submitted_by_username},
            {"label": "Submitted on", "datetime": submission.requested_at},
            {"label": "QC result", "value": "Passed" if submission.job.job_status == "ok" else "Not passed"},
            {"label": "Delivery plan", "value": "Revision {}".format(submission.product_release.revision)},
        ],
    }
    return render(request, "dashboard/submissions/detail.html", {
        **_submission_workspace_navigation(access, submission),
        "submission": submission, "form": form, "can_review": can_review,
        "can_decide": detail["decision"]["can_decide"],
        "detail": detail, "submission_summary": summary,
        "conflict": conflict,
        "candidates": visible_submissions(access).filter(
            product_unit=submission.product_unit, publication_state="published",
        ).exclude(pk=submission.pk).order_by("requested_at") if can_review else [],
        "events": events,
        "review_feedback": current_review_feedback(submission, events=events),
        "correction": correction_context(submission, access, events=events),
        "files": files, "storage_available": storage_available,
    })


def submission_file(request, submission_id, filename):
    submission = get_object_or_404(visible_submissions(access_for_request(request)), pk=submission_id)
    try:
        stream = open_submission_file(submission, filename)
    except (ArtifactUnavailable, OSError) as exc:
        raise Http404("The retained submission file is unavailable or failed its integrity check.") from exc
    return FileResponse(stream, as_attachment=True, filename=PurePosixPath(filename).name)
