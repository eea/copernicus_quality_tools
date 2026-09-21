"""Scoped delivery-submission candidate review in Django admin."""

from django.contrib import admin
from django.contrib import messages

from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard.models import DeliverySubmission
from qc_tool.frontend.dashboard.models import SubmissionConflict
from qc_tool.frontend.dashboard.services.submissions import SubmissionError
from qc_tool.frontend.dashboard.services.submissions import (
    resolve_submission_conflict,
)

from ..scope import release_scope
from ..scope import ScopedCatalogHistoryAdmin


@admin.register(DeliverySubmission)
class DeliverySubmissionAdmin(ScopedCatalogHistoryAdmin):
    """Read-only candidates with one explicit conflict-resolution action."""

    list_display = (
        "submission_uuid",
        "product_unit_code",
        "verified_product_unit_code",
        "delivery_filename",
        "uploader",
        "qc_requester",
        "submitted_by_username",
        "publication_state",
        "review_state",
        "content_relationship",
        "published_at",
    )
    list_filter = ("publication_state", "review_state", "request_channel")
    search_fields = (
        "submission_uuid",
        "delivery__filename",
        "delivery__user__username",
        "job__job_uuid",
        "product_unit_code",
        "verified_product_unit_code",
        "input_digest",
    )
    readonly_fields = tuple(
        field.name for field in DeliverySubmission._meta.fields
    )
    actions = ("resolve_with_selected_candidate",)

    def get_queryset(self, request):
        return release_scope(
            super().get_queryset(request).select_related(
                "delivery__user",
                "job__requested_by",
                "product_unit__product_release__product",
            ),
            request,
            prefix="product_release__",
        )

    def _product_unit_for_object(self, obj):
        return obj.product_unit

    @admin.display(description="File")
    def delivery_filename(self, obj):
        return obj.delivery.filename

    @admin.display(description="Uploader")
    def uploader(self, obj):
        return obj.delivery.user.username if obj.delivery.user_id else "—"

    @admin.display(description="QC requester")
    def qc_requester(self, obj):
        return obj.job.requested_by_username or "—"

    @admin.display(description="Candidate relationship")
    def content_relationship(self, obj):
        if not obj.input_digest:
            return "Checksum unavailable"
        has_exact_duplicate = (
            DeliverySubmission.objects.filter(
                product_unit_id=obj.product_unit_id,
                publication_state=(
                    DeliverySubmission.PublicationState.PUBLISHED
                ),
                input_digest=obj.input_digest,
            )
            .exclude(pk=obj.pk)
            .exists()
        )
        if has_exact_duplicate:
            return "Exact-content duplicate"
        return "Distinct content"

    def has_resolve_permission(self, request):
        access = access_for_request(request)
        return bool(access.is_administrator or access.is_product_manager)

    @admin.action(
        description="Resolve product unit conflict using the selected candidate",
        permissions=("resolve",),
    )
    def resolve_with_selected_candidate(self, request, queryset):
        candidate = self._single_candidate(request, queryset)
        if candidate is None:
            return
        conflict = SubmissionConflict.objects.filter(
            product_unit_id=candidate.product_unit_id,
            state=SubmissionConflict.State.OPEN,
        ).first()
        if conflict is None:
            self.message_user(
                request,
                "The selected candidate has no open product unit conflict.",
                level=messages.ERROR,
            )
            return
        try:
            result = resolve_submission_conflict(
                conflict_id=conflict.pk,
                selected_submission_id=candidate.pk,
                actor=request.user,
                account_access=access_for_request(request),
                expected_version=conflict.version,
                notes=(
                    "Resolved from the scoped Django admin candidate list."
                ),
            )
        except SubmissionError as exc:
            self.message_user(request, exc.message, level=messages.ERROR)
            return
        self.message_user(
            request,
            "Conflict {} resolved at version {}.".format(
                result.conflict_id,
                result.version,
            ),
            level=messages.SUCCESS,
        )

    def _single_candidate(self, request, queryset):
        selected = list(queryset[:2])
        if len(selected) == 1:
            return selected[0]
        self.message_user(
            request,
            "Select exactly one published submission candidate.",
            level=messages.ERROR,
        )
        return None
