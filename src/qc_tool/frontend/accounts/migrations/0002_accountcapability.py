from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_create_role_groups"),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountCapability",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
            ],
            options={
                "managed": False,
                "default_permissions": (),
                "permissions": (
                    ("view_deliveries", "Can view deliveries"),
                    ("upload_delivery", "Can upload deliveries"),
                    ("run_qc", "Can run quality control"),
                    ("delete_delivery", "Can delete deliveries"),
                    ("submit_delivery", "Can submit deliveries"),
                    ("change_password", "Can change own password"),
                    (
                        "manage_configuration",
                        "Can manage QC Tool configuration",
                    ),
                    (
                        "view_country_deliveries",
                        "Can view deliveries in assigned country",
                    ),
                    (
                        "view_product_deliveries",
                        "Can view deliveries in assigned product family",
                    ),
                    (
                        "view_country_aggregate_report",
                        "Can view aggregate reports for assigned country",
                    ),
                    (
                        "view_product_aggregate_report",
                        "Can view aggregate reports for assigned product family",
                    ),
                ),
            },
        ),
    ]
