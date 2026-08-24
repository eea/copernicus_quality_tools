from django.contrib import admin

from qc_tool.frontend.accounts.authorization.roles import Role


class RoleListFilter(admin.SimpleListFilter):
    title = "role"
    parameter_name = "role"

    def lookups(self, request, model_admin):
        return tuple(
            (role.value, role.value.replace("_", " ").title())
            for role in Role
        )

    def queryset(self, request, queryset):
        if self.value() not in Role.values():
            return queryset
        return queryset.filter(groups__name=self.value()).distinct()
