from django.contrib import admin

from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.dashboard.models import S3Info


admin.site.register(Delivery)
admin.site.register(S3Info)
admin.site.register(Job)
