from django.db import models


class AccountCapability(models.Model):
    """Content-type anchor for QC Tool permissions; it stores no rows."""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = (
            ("view_deliveries", "Can view deliveries"),
            ("upload_delivery", "Can upload deliveries"),
            ("run_qc", "Can run quality control"),
            ("delete_delivery", "Can delete deliveries"),
            ("submit_delivery", "Can submit deliveries"),
            ("change_password", "Can change own password"),
            ("manage_own_account", "Can manage own account"),
            ("manage_api_credential", "Can manage own API credential"),
            ("manage_configuration", "Can manage QC Tool configuration"),
            (
                "view_product_deliveries",
                "Can view deliveries in assigned products",
            ),
            (
                "view_product_aggregate_report",
                "Can view aggregate reports for assigned products",
            ),
        )
