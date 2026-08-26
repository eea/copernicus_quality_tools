"""Scoped conflict and conflict-event history in Django admin."""

from django.contrib import admin

from qc_tool.frontend.dashboard.models import SubmissionConflict
from qc_tool.frontend.dashboard.models import SubmissionConflictEvent

from ..scope import release_scope
from ..scope import ScopedCatalogHistoryAdmin


@admin.register(SubmissionConflict)
class SubmissionConflictAdmin(ScopedCatalogHistoryAdmin):
    list_display = (
        "id",
        "product_aoi",
        "state",
        "version",
        "selected_submission",
        "opened_at",
        "resolved_at",
        "resolved_by_username",
    )
    list_filter = ("state",)
    search_fields = (
        "product_aoi__aoi_code",
        "product_aoi__product_release__release_key",
    )
    readonly_fields = tuple(
        field.name for field in SubmissionConflict._meta.fields
    )

    def get_queryset(self, request):
        return release_scope(
            super().get_queryset(request).select_related(
                "product_aoi__product_release__product"
            ),
            request,
            prefix="product_aoi__product_release__",
        )

    def _product_aoi_for_object(self, obj):
        return obj.product_aoi


@admin.register(SubmissionConflictEvent)
class SubmissionConflictEventAdmin(ScopedCatalogHistoryAdmin):
    list_display = (
        "conflict",
        "version",
        "event_type",
        "selected_submission",
        "actor_username",
        "created_at",
    )
    list_filter = ("event_type",)
    readonly_fields = tuple(
        field.name for field in SubmissionConflictEvent._meta.fields
    )

    def get_queryset(self, request):
        return release_scope(
            super().get_queryset(request).select_related(
                "conflict__product_aoi__product_release__product"
            ),
            request,
            prefix="conflict__product_aoi__product_release__",
        )

    def _product_aoi_for_object(self, obj):
        return obj.conflict.product_aoi
