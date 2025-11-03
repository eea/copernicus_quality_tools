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


# Register your models here.
admin.site.register(Delivery)
admin.site.register(S3Info)
admin.site.register(Job)

# Re-register UserAdmin
admin.site.unregister(User)
admin.site.register(User, UserAdmin)
