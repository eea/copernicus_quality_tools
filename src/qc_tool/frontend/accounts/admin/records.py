"""Administrator-owned product assignments and secret-free token revocation."""

from django.contrib import admin
from django.core.exceptions import PermissionDenied

from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.accounts.models import PersonalAccessToken, UserProductGrant
from qc_tool.frontend.accounts.services.api_tokens import delete_personal_access_token
from qc_tool.frontend.accounts.services.product_grants import save_product_grant

from .products import UserProductGrantForm


class AdministratorRecordAdmin(admin.ModelAdmin):
    """Keep account child records unavailable to generic staff permissions."""

    actions = None

    def has_module_permission(self, request):
        return access_for_request(request).is_administrator

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        return self.has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_delete_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def delete_queryset(self, request, queryset):
        raise PermissionDenied("Review and confirm one record before deleting it.")


@admin.register(PersonalAccessToken)
class PersonalAccessTokenAdmin(AdministratorRecordAdmin):
    """Inspect captured access and revoke one token through its owner service."""

    list_display = ("id", "name", "user", "token_hint", "created_at", "last_used_at")
    search_fields = ("name", "user__username", "user__email", "token_hint")
    list_select_related = ("user",)
    fields = (
        "id", "user", "name", "token_hint", "created_at", "last_used_at",
        "permission_snapshot", "role_snapshot", "product_idents_snapshot",
        "is_administrator_snapshot",
    )
    readonly_fields = fields
    exclude = ("secret_digest",)

    def get_queryset(self, request):
        return super().get_queryset(request).defer("secret_digest")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def delete_model(self, request, obj):
        # Authorization belongs to this Admin; the shared service serializes
        # revocation with issuance and restricts the deletion to this owner.
        delete_personal_access_token(obj.user, obj.pk)


class UserProductGrantAdminForm(UserProductGrantForm):
    class Meta(UserProductGrantForm.Meta):
        fields = ("user", "product_ident")


@admin.register(UserProductGrant)
class UserProductGrantAdmin(AdministratorRecordAdmin):
    """Validate assignments without moving a saved grant between accounts."""

    form = UserProductGrantAdminForm
    list_display = ("id", "user", "product_ident", "created_by", "created_at")
    search_fields = ("user__username", "user__email", "product_ident")
    list_filter = ("product_ident",)
    list_select_related = ("user", "created_by")
    autocomplete_fields = ("user",)
    fields = ("user", "product_ident", "created_by", "created_at")
    readonly_fields = ("created_by", "created_at")

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields + (("user",) if obj is not None else ())

    def save_model(self, request, obj, form, change):
        if change:
            original = UserProductGrant.objects.select_for_update().get(pk=obj.pk)
            obj.user_id = original.user_id
            obj.created_by_id = original.created_by_id
        save_product_grant(obj, created_by=request.user)
