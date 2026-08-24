from django.contrib import admin

from qc_tool.frontend.accounts.models import UserRegionGrant


class UserRegionGrantInline(admin.TabularInline):
    model = UserRegionGrant
    fk_name = "user"
    fields = ("aoi_code", "created_at", "created_by")
    readonly_fields = ("created_at", "created_by")
    extra = 1
    verbose_name = "Region grant"
    verbose_name_plural = "Region grants — exact AOI codes"

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "aoi_code":
            field.label = "Exact AOI code"
            field.help_text = (
                "Pending the AOI catalog PR, codes are stored as opaque "
                "identifiers without validation or normalization."
            )
        return field

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("created_by")
