"""Use QC Tool's administration shell with Django's existing admin app."""

from django.contrib.admin.apps import AdminConfig


class QCAdminConfig(AdminConfig):
    default_site = "qc_tool.frontend.admin_site.QCAdminSite"
