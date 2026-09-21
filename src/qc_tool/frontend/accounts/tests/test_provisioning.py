from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import CommandError
from django.core.management import call_command
from django.test import TestCase

from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.accounts.services.users import provision_user


class UserProvisioningTests(TestCase):
    @patch(
        "qc_tool.frontend.accounts.services.products.available_product_descriptions",
        return_value={"clc2024": "CLC", "general_raster": "General raster"},
    )
    def test_service_validates_and_creates_product_grants_atomically(self, _get):
        result = provision_user(
            username="product-service-user",
            password="service-password",
            product_idents=("clc2024", "general_raster", "clc2024"),
        )

        self.assertEqual(
            set(
                UserProductGrant.objects.filter(user=result.user).values_list(
                    "product_ident",
                    flat=True,
                )
            ),
            {"clc2024", "general_raster"},
        )

        with self.assertRaises(ValidationError):
            provision_user(
                username="invalid-product-service-user",
                password="service-password",
                product_idents=("not-a-product",),
            )
        self.assertFalse(
            get_user_model().objects.filter(
                username="invalid-product-service-user"
            ).exists()
        )

    def test_service_creates_account_and_canonical_roles(self):
        result = provision_user(
            username="service-user",
            password="service-password",
            email="service@example.test",
            groups=(Role.PRODUCT_MANAGER.value,),
        )

        self.assertTrue(result.created)
        self.assertTrue(result.user.check_password("service-password"))
        self.assertEqual(result.user.email, "service@example.test")
        self.assertEqual(
            set(result.user.groups.values_list("name", flat=True)),
            {
                Role.DEFAULT.value,
                Role.PRODUCT_MANAGER.value,
            },
        )

    @patch(
        "qc_tool.frontend.accounts.services.products.available_product_descriptions",
        return_value={"clc2024": "CLC", "general_raster": "General raster"},
    )
    def test_command_accepts_repeatable_exact_product_ids(self, _get):
        output = StringIO()

        call_command(
            "create_default_user",
            "--username",
            "product-command-user",
            "--password",
            "command-password",
            "--product",
            "clc2024",
            "--product",
            "general_raster",
            stdout=output,
        )

        user = get_user_model().objects.get(username="product-command-user")
        self.assertIn("created successfully", output.getvalue())
        self.assertEqual(
            set(user.product_grants.values_list("product_ident", flat=True)),
            {"clc2024", "general_raster"},
        )

    def test_service_assigns_default_when_no_extra_role_is_requested(self):
        result = provision_user(
            username="default-service-user",
            password="service-password",
        )

        self.assertEqual(
            set(result.user.groups.values_list("name", flat=True)),
            {Role.DEFAULT.value},
        )

    def test_service_assigns_default_and_admin_to_superusers(self):
        result = provision_user(
            username="service-superuser",
            password="service-password",
            is_superuser=True,
        )

        self.assertEqual(
            set(result.user.groups.values_list("name", flat=True)),
            {Role.DEFAULT.value, Role.ADMIN.value},
        )

    def test_service_is_idempotent_for_an_existing_username(self):
        first = provision_user(
            username="idempotent-user",
            password="original-password",
        )

        second = provision_user(
            username="idempotent-user",
            password="replacement-password",
            groups=(Role.PRODUCT_MANAGER.value,),
        )

        self.assertFalse(second.created)
        self.assertEqual(second.user.pk, first.user.pk)
        self.assertEqual(
            get_user_model().objects.filter(username="idempotent-user").count(),
            1,
        )
        first.user.refresh_from_db()
        self.assertTrue(first.user.check_password("original-password"))
        self.assertEqual(
            set(first.user.groups.values_list("name", flat=True)),
            {Role.DEFAULT.value},
        )

    def test_command_delegates_roles_to_service(self):
        output = StringIO()
        arguments = (
            "--username",
            "command-user",
            "--password",
            "command-password",
            "--group",
            Role.PRODUCT_MANAGER.value,
        )

        call_command("create_default_user", *arguments, stdout=output)
        user = get_user_model().objects.get(username="command-user")

        self.assertIn("created successfully", output.getvalue())
        self.assertEqual(
            set(user.groups.values_list("name", flat=True)),
            {
                Role.DEFAULT.value,
                Role.PRODUCT_MANAGER.value,
            },
        )

        duplicate_output = StringIO()
        call_command("create_default_user", *arguments, stdout=duplicate_output)
        self.assertIn("already exists", duplicate_output.getvalue())
        self.assertEqual(
            get_user_model().objects.filter(username="command-user").count(),
            1,
        )

    def test_command_rejects_removed_region_manager_group(self):
        with self.assertRaises(CommandError):
            call_command(
                "create_default_user",
                "--username",
                "removed-role-user",
                "--password",
                "command-password",
                "--group",
                "region_manager",
            )

        self.assertFalse(
            get_user_model().objects.filter(username="removed-role-user").exists()
        )

    def test_command_rejects_removed_geographic_account_options(self):
        for option in ("--country", "--region", "--region-code", "--aoi-code"):
            with self.subTest(option=option), self.assertRaises(CommandError):
                call_command(
                    "create_default_user", "--username", "removed-scope-user",
                    "--password", "command-password", option, "CZ",
                )
        self.assertFalse(get_user_model().objects.filter(username="removed-scope-user").exists())
