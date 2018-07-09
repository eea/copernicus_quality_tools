# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.contrib import admin

from .models import Job
from .models import Delivery

# Register your models here.
admin.site.register(Job)
admin.site.register(Delivery)
