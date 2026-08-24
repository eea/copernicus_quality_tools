from io import StringIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from qc_tool.frontend.accounts.authorization.roles import Role


class StartupAccountCommandTests(TestCase):
    def run_command(self, *arguments):
        output = StringIO()
        call_command("create_default_user", *arguments, stdout=output)
        return output.getvalue()

    def test_startup_script_uses_the_exact_supported_command_contracts(self):
        repository_root = Path(__file__).resolve().parents[5]
        startup_lines = {
            line.strip()
            for line in repository_root.joinpath(
                "docker",
                "run_frontend.sh",
            ).read_text().splitlines()
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
