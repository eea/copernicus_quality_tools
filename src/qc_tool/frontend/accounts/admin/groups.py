from django.contrib import admin
from django.contrib.admin.sites import NotRegistered
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.models import Group
from django.db.models import Count

from qc_tool.frontend.accounts.authorization.roles import Role


class AccountGroupAdmin(BaseGroupAdmin):
    """Expose role membership without allowing canonical roles to drift."""

    list_display = ("name", "member_count")
    search_fields = ("name", "user__username", "user__email")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(member_total=Count("user"))

    def get_readonly_fields(self, request, obj=None):
        if obj is not None and obj.name in Role.values():
            return ("name",)
        return ()

    def get_fieldsets(self, request, obj=None):
        if obj is not None and obj.name in Role.values():
            return (
                (
                    None,
                    {
                        "fields": ("name",),
                        "description": (
                            "This role's permissions are managed by QC Tool. "
                            "Assign user-specific exceptions from the Users page."
                        ),
                    },
                ),
            )
        return super().get_fieldsets(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.name in Role.values():
            return False
        return super().has_delete_permission(request, obj)

    def save_model(self, request, obj, form, change):
        if obj.pk:
            original_name = Group.objects.filter(pk=obj.pk).values_list(
                "name",
                flat=True,
            ).first()
            if original_name in Role.values():
                obj.name = original_name
        super().save_model(request, obj, form, change)

    def delete_model(self, request, obj):
        if obj.name not in Role.values():
            super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        deletable = queryset.exclude(name__in=Role.values())
        super().delete_queryset(request, deletable)

    @admin.display(description="Members", ordering="member_total")
    def member_count(self, group):
        return group.member_total


try:
    admin.site.unregister(Group)
except NotRegistered:
    pass
admin.site.register(Group, AccountGroupAdmin)
