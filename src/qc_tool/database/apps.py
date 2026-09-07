"""Django discovery for the application-wide database command; owns no models."""

from django.apps import AppConfig


class DatabaseConfig(AppConfig):
    name = "qc_tool.database"
    label = "qc_database"
    verbose_name = "QC Tool database lifecycle"
