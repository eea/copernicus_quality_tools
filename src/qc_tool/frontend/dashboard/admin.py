"""Core Django-admin registrations and focused domain feature imports."""

from django.contrib import admin

from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.dashboard.models import S3Info


@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "filename",
        "user",
        "product_ident",
        "product_unit_code",
        "date_uploaded",
        "is_deleted",
    )
    search_fields = ("filename", "product_ident", "product_unit_code", "user__username")
    readonly_fields = tuple(field.name for field in Delivery._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        # Upload, deletion, QC projection, and submission each have their own
        # row-locked service. Direct edits could bypass those invariants.
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = (
        "job_uuid",
        "delivery",
        "product_ident",
        "product_unit_code",
        "job_status",
        "date_created",
    )
    search_fields = (
        "job_uuid",
        "delivery__filename",
        "product_ident",
        "product_unit_code",
    )
    readonly_fields = tuple(field.name for field in Job._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        # Job lifecycle changes must acquire the Delivery lock and refresh its
        # denormalized product unit/product projection through the domain service.
        return False

    def has_delete_permission(self, request, obj=None):
        # Jobs are retained logs. Only deleting their delivery removes them.
        return False


@admin.register(S3Info)
class S3InfoAdmin(admin.ModelAdmin):
    """Expose S3 location metadata without rendering stored credentials."""

    list_display = (
        "id",
        "host",
        "bucketname",
        "key_prefix",
        "credential_status",
    )
    fields = (
        "id",
        "host",
        "bucketname",
        "key_prefix",
        "credential_status",
    )
    readonly_fields = fields
    search_fields = (
        "host",
        "bucketname",
        "key_prefix",
    )

    def get_queryset(self, request):
        return super().get_queryset(request).defer("access_key", "secret_key")

    @admin.display(description="Credentials")
    def credential_status(self, _instance):
        return "Configured (hidden)"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        # Deleting S3Info cascades to its Delivery. Deletion belongs to the
        # audited delivery workflow, not the generic Django admin.
        return False


# Importing these modules performs their decorator-based registrations while
# keeping catalog and submission review logic out of this discovery boundary.
from qc_tool.frontend.dashboard.admin_features import catalog as _catalog_admin
from qc_tool.frontend.dashboard.admin_features import (
    submissions as _submissions_admin,
)


__all__ = [
    "DeliveryAdmin",
    "JobAdmin",
    "S3InfoAdmin",
]
