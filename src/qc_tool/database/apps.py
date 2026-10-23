"""Application database lifecycle and durable transfer commit receipts."""

from django.apps import AppConfig


class DatabaseConfig(AppConfig):
    name = "qc_tool.database"
    label = "qc_database"
    verbose_name = "QC Tool database lifecycle"
