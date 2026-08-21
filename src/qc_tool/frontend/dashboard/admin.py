# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import Job

from qc_tool.frontend.dashboard.models import ApiUser
from qc_tool.frontend.dashboard.models import S3Info
from qc_tool.frontend.dashboard.models import UserProfile

# Define an inline admin descriptor for ApiUser model
# which acts a bit like a singleton
class ApiUserInline(admin.StackedInline):
    model = ApiUser
    can_delete = False
    verbose_name_plural = "apiuser"

# Define an inline admin descriptor for UserProfile model
class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = "userprofile"

# Define a new User admin
class UserAdmin(BaseUserAdmin):
    inlines = [ApiUserInline, UserProfileInline]


class DeliveryAdmin(admin.ModelAdmin):
    fields = (
        "id",
        "user",
        "filename",
        "size_bytes",
        "date_uploaded",
        "date_submitted",
        "product_ident",
        "product_description",
        "aoi_code",
        "is_deleted",
        "s3",
    )
    list_display = fields
    list_display_links = ("id",)
    readonly_fields = ("id", "aoi_code")
    list_select_related = ("user", "s3")


class JobAdmin(admin.ModelAdmin):
    fields = (
        "job_uuid",
        "delivery",
        "date_created",
        "date_started",
        "date_finished",
        "job_status",
        "product_ident",
        "product_description",
        "aoi_code",
        "skip_steps",
        "worker_url",
    )
    list_display = fields
    list_display_links = ("job_uuid",)
    readonly_fields = ("job_uuid", "aoi_code")
    list_select_related = ("delivery", "delivery__user")


# Register your models here.
admin.site.register(Delivery, DeliveryAdmin)
admin.site.register(S3Info)
admin.site.register(Job, JobAdmin)

# Re-register UserAdmin
admin.site.unregister(User)
admin.site.register(User, UserAdmin)
