from django.contrib import admin
from django.contrib.admin.sites import NotRegistered
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.db.models import Prefetch

from qc_tool.frontend.accounts.admin.filters import RoleListFilter
from qc_tool.frontend.accounts.admin.products import UserProductGrantInline
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import PersonalAccessToken
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.accounts.services.product_grants import save_product_grant
from qc_tool.frontend.accounts.services.role_permissions import (
    capability_permissions,
)


class PersonalAccessTokenInline(admin.TabularInline):
    """List and revoke named tokens without exposing stored digests."""

    model = PersonalAccessToken
    fields = ("name", "token_hint", "created_at", "last_used_at")
    readonly_fields = fields
    exclude = (
        "secret_digest",
        "permission_snapshot",
        "role_snapshot",
        "product_idents_snapshot",
        "is_administrator_snapshot",
    )
    can_delete = True
    extra = 0
    verbose_name_plural = "Personal API tokens (secrets are never stored)"

    def has_add_permission(self, request, obj=None):
        # Credentials must be issued through the one-time self-service view.
        return False


class AccountUserAdmin(BaseUserAdmin):
    """Keep all user-related Django Admin composition in accounts."""

    inlines = (
        PersonalAccessTokenInline,
        UserProductGrantInline,
    )
    list_display = (
        "username",
        "email",
        "role_names",
        "product_idents",
        "direct_qc_permissions",
        "is_active",
    )
    list_filter = (
        RoleListFilter,
        ("product_grants__product_ident", admin.AllValuesFieldListFilter),
        "is_active",
    )
    search_fields = (
        "username",
        "email",
        "first_name",
        "last_name",
        "product_grants__product_ident__exact",
    )
    ordering = ("username",)
    filter_horizontal = ("groups", "user_permissions")
    readonly_fields = ("is_staff", "last_login", "date_joined")

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (
            "Personal information",
            {"fields": ("first_name", "last_name", "email")},
        ),
        (
            "Roles and permissions",
            {
                "fields": (
                    "groups",
                    "user_permissions",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                )
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "password1", "password2"),
            },
        ),
        (
            "Roles and permissions",
            {"fields": ("groups", "user_permissions")},
        ),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .prefetch_related(
                "groups",
                Prefetch(
                    "user_permissions",
                    queryset=capability_permissions(),
                    to_attr="direct_qc_capabilities",
                ),
                Prefetch(
                    "product_grants",
                    queryset=UserProductGrant.objects.order_by(
                        "product_ident",
                        "pk",
                    ),
                    to_attr="assigned_product_grants",
                ),
            )
        )

    def save_formset(self, request, form, formset, change):
        if formset.model is not UserProductGrant:
            return super().save_formset(request, form, formset, change)

        instances = formset.save(commit=False)
        for deleted in formset.deleted_objects:
            deleted.delete()
        for instance in instances:
            save_product_grant(instance, created_by=request.user)
        formset.save_m2m()

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.remote_field.model is Group:
            kwargs["queryset"] = Group.objects.filter(
                name__in=Role.values(),
            ).order_by("name")
        elif db_field.name == "user_permissions":
            kwargs["queryset"] = capability_permissions(
                using=kwargs.get("using") or "default",
            )

        field = super().formfield_for_manytomany(
            db_field,
            request,
            **kwargs,
        )
        if db_field.remote_field.model is Group:
            field.label = "Roles"
        elif db_field.name == "user_permissions":
            field.label = "Additional QC permissions"
            field.help_text = (
                "Optional QC Tool capabilities granted directly in addition "
                "to role permissions."
            )
        return field

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        if request.user.is_superuser or obj is None:
            return fieldsets

        return tuple(
            (
                title,
                {
                    **options,
                    "fields": tuple(
                        field
                        for field in options.get("fields", ())
                        if field != "is_superuser"
                    ),
                },
            )
            for title, options in fieldsets
        )

    def has_change_permission(self, request, obj=None):
        allowed = super().has_change_permission(request, obj)
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return allowed

    def has_delete_permission(self, request, obj=None):
        """Protect delivery and QC history from Django's cascading delete.

        Administrators should deactivate an account with ``is_active``.  A
        deliberate archival/deletion workflow can be added later once domain
        retention rules and ownership reassignment are explicit.
        """

        return False

    @admin.display(description="Roles")
    def role_names(self, user):
        recognized = Role.values()
        names = [
            group.name.replace("_", " ").title()
            for group in user.groups.all()
            if group.name in recognized
        ]
        return ", ".join(sorted(names)) or "—"

    @admin.display(description="Product grants")
    def product_idents(self, user):
        grants = getattr(user, "assigned_product_grants", None)
        if grants is None:
            grants = user.product_grants.order_by("product_ident", "pk")
        return ", ".join(grant.product_ident for grant in grants) or "—"

    @admin.display(description="Direct QC permissions")
    def direct_qc_permissions(self, user):
        permissions = getattr(user, "direct_qc_capabilities", None)
        if permissions is None:
            permission_ids = capability_permissions().values_list("pk", flat=True)
            permissions = user.user_permissions.filter(pk__in=permission_ids)
        return ", ".join(sorted(item.name for item in permissions)) or "—"


user_model = get_user_model()
try:
    admin.site.unregister(user_model)
except NotRegistered:
    pass
admin.site.register(user_model, AccountUserAdmin)
