# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.contrib import admin
from .models import Job
from .models import File
from .models import FileFormat
from .models import Product

# Register your models here.
admin.site.register(Job)
admin.site.register(FileFormat)
admin.site.register(File)
admin.site.register(Product)
