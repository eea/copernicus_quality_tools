"""
WSGI config for qctool project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/1.11/howto/deployment/wsgi/
"""
import os
from threading import Thread

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "qc_tool.frontend.settings")

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()

# Run refresh_job_statuses service.
if os.environ.get("REFRESH_JOB_STATUSES_BACKGROUND", "yes") == "yes":
    from qc_tool.frontend.dashboard.views.jobs.status import refresh_job_statuses
    t = Thread(target=refresh_job_statuses, daemon=True)
    t.start()
