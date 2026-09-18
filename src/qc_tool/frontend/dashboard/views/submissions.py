"""Owner submission tracking and assigned-manager review workspace."""

from pathlib import PurePosixPath

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard.forms.submission_reviews import SubmissionReviewForm
from qc_tool.frontend.dashboard.models import SubmissionConflict
from qc_tool.frontend.dashboard.services.artifacts import ArtifactUnavailable
from qc_tool.frontend.dashboard.services.submissions import SubmissionError, resolve_submission_conflict
from qc_tool.frontend.dashboard.services.submissions.access import visible_submissions
from qc_tool.frontend.dashboard.services.submissions.artifacts import submission_inventory, open_submission_file
from qc_tool.frontend.dashboard.services.submissions.presentation import correction_context, current_review_feedback
from qc_tool.frontend.dashboard.services.submissions.review import review_submission


def submission_queue(request):
    access = access_for_request(request)
    can_review = access.is_administrator or access.is_product_manager
    queryset = visible_submissions(access)
    product = request.GET.get("product", "")
    if product:
        queryset = queryset.filter(product_release__product__ident=product)
    delivery = request.GET.get("delivery", "")
    if delivery:
        queryset = queryset.filter(delivery_id=int(delivery)) if delivery.isdecimal() and len(delivery) < 19 else queryset.none()
    state = request.GET.get("state", "pending" if can_review else "all")
    if state not in {"pending", "accepted", "rejected", "all"}:
        state = "pending"
    if state == "pending":
        queryset = queryset.filter(review_state__in=("pending", "conflict"))
    elif state != "all":
        queryset = queryset.filter(review_state=state)
    page = Paginator(queryset.order_by("requested_at", "pk"), 30).get_page(request.GET.get("page"))
    return render(request, "dashboard/submissions/index.html", {
        "review_items": page, "selected_state": state, "selected_product": product,
        "selected_delivery": delivery,
        "can_review": can_review,
    })


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
    return render(request, "dashboard/submissions/detail.html", {
        "submission": submission, "form": form, "can_review": can_review,
        "can_decide": can_review and submission.publication_state == "published"
            and submission.review_state in {"pending", "conflict"},
        "conflict": conflict,
        "candidates": visible_submissions(access).filter(
            product_unit=submission.product_unit, publication_state="published",
        ).exclude(pk=submission.pk).order_by("requested_at"),
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
