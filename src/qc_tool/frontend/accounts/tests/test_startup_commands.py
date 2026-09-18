from io import StringIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from qc_tool.frontend.accounts.authorization.access import access_for
from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.accounts.authorization.permissions import DEFAULT_PERMISSIONS
from qc_tool.frontend.accounts.authorization.roles import Role

class StartupAccountCommandTests(TestCase):
    def run_command(self, *arguments):
        output = StringIO()
        call_command("create_default_user", *arguments, stdout=output)
        return output.getvalue()

    def test_startup_script_uses_the_exact_supported_command_contracts(self):
        repository_root = Path(__file__).resolve().parents[5]
        startup_script = repository_root.joinpath(
            "docker",
            "run_frontend.sh",
        ).read_text()
        startup_lines = {
            " ".join(line.split())
            for line in startup_script.replace("\\\n", " ").splitlines()
        }

        self.assertIn(
            "python3 -m qc_tool.frontend.manage create_default_user "
            "--username admin --password admin --superuser",
            startup_lines,
        )
        self.assertIn(
            "python3 -m qc_tool.frontend.manage create_default_user "
            "--username guest --password guest",
            startup_lines,
        )
        self.assertIn(
            "python3 -m qc_tool.frontend.manage create_default_user "
            "--username product_manager --password product_manager "
            "--group product_manager",
            startup_lines,
        )
        account_commands = {
            line
            for line in startup_lines
            if "create_default_user --username" in line
        }
        self.assertEqual(len(account_commands), 3)
        self.assertNotIn(
            "python3 -m qc_tool.frontend.manage create_default_user "
            "--username guest2 --password guest2",
            startup_lines,
        )
        self.assertNotIn(
            "python3 -m qc_tool.frontend.manage create_default_user "
            "--username guest3 --password guest3",
            startup_lines,
        )

    def test_startup_admin_contract_creates_a_canonical_admin(self):
        output = self.run_command(
            "--username",
            "admin",
            "--password",
            "admin",
            "--superuser",
        )

        user = get_user_model().objects.get(username="admin")
        self.assertIn("created successfully", output)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password("admin"))
        self.assertEqual(
            set(user.groups.values_list("name", flat=True)),
            {Role.DEFAULT.value, Role.ADMIN.value},
        )
        access = access_for(user)
        self.assertTrue(access.is_administrator)
        self.assertEqual(access.permissions, frozenset(AccountPermission))

    def test_startup_guest_contract_uses_the_default_role(self):
        self.run_command(
            "--username",
            "guest",
            "--password",
            "guest",
        )

        user = get_user_model().objects.get(username="guest")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password("guest"))
        self.assertEqual(
            set(user.groups.values_list("name", flat=True)),
            {Role.DEFAULT.value},
        )
        access = access_for(user)
        self.assertFalse(access.is_administrator)
        self.assertFalse(access.is_product_manager)
        self.assertEqual(access.permissions, DEFAULT_PERMISSIONS)

    def test_startup_product_manager_starts_without_product_assignments(self):
        output = self.run_command(
            "--username",
            "product_manager",
            "--password",
            "product_manager",
            "--group",
            Role.PRODUCT_MANAGER.value,
        )

        user = get_user_model().objects.get(username="product_manager")
        self.assertIn("created successfully", output)
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password("product_manager"))
        self.assertEqual(
            set(user.groups.values_list("name", flat=True)),
            {Role.DEFAULT.value, Role.PRODUCT_MANAGER.value},
        )
        self.assertEqual(
            set(user.product_grants.values_list("product_ident", flat=True)),
            set(),
        )

        access = access_for(user)
        self.assertFalse(access.is_administrator)
        self.assertTrue(access.is_product_manager)
        self.assertFalse(access.can_view_product_deliveries)
        self.assertFalse(access.can_view_product_aggregate_report)
        self.assertFalse(access.can_view_other_users_deliveries)
        self.assertFalse(access.can_manage_configuration)
        self.assertEqual(
            access.product_idents,
            frozenset(),
        )

    def test_duplicate_startup_command_preserves_the_existing_password(self):
        self.run_command(
            "--username",
            "guest",
            "--password",
            "original-password",
        )
        output = self.run_command(
            "--username",
            "guest",
            "--password",
            "replacement-password",
        )

        user = get_user_model().objects.get(username="guest")
        self.assertIn("already exists", output)
        self.assertTrue(user.check_password("original-password"))
        self.assertFalse(user.check_password("replacement-password"))
