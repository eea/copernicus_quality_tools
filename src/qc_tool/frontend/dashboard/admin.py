# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.contrib import admin
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import Job

# Register your models here.
admin.site.register(Delivery)
admin.site.register(Job)
