from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "qc_tool.frontend.accounts"
    verbose_name = "QC Tool accounts"

    def ready(self):
        from qc_tool.frontend.accounts.admin.signals import (
            connect_account_admin_signals,
        )
        from qc_tool.frontend.accounts.signals import connect_user_role_signals

        connect_user_role_signals(self)
        connect_account_admin_signals(self)
