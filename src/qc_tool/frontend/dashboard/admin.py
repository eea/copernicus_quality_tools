# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.contrib import admin

from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.dashboard.models import Delivery

# Register your models here.
admin.site.register(Job)
admin.site.register(Delivery)
