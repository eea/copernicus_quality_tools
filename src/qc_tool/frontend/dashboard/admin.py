# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.contrib import admin
from .models import File
from .models import FileFormat
from .models import Product
from .models import CheckingSession

# Register your models here.
admin.site.register(FileFormat)
admin.site.register(File)
admin.site.register(Product)
admin.site.register(CheckingSession)
