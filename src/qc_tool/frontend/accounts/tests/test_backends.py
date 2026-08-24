from django.contrib.auth import get_user_model
from django.test import TestCase

from qc_tool.frontend.accounts.authentication.backends import (
    CaseInsensitiveBackend,
)


class CaseInsensitiveBackendTests(TestCase):
    password = "correct-horse-battery-staple"

    def setUp(self):
        self.backend = CaseInsensitiveBackend()

    def test_authenticates_active_user_without_username_case_sensitivity(self):
        user = get_user_model().objects.create_user(
            username="MixedCase",
            password=self.password,
        )

        authenticated = self.backend.authenticate(
            None,
            username="mixedcase",
            password=self.password,
        )

        self.assertEqual(authenticated, user)
        self.assertIsNone(
            self.backend.authenticate(
                None,
                username="MIXEDCASE",
                password="incorrect-password",
            )
        )

    def test_rejects_inactive_user(self):
        get_user_model().objects.create_user(
            username="InactiveUser",
            password=self.password,
            is_active=False,
        )

        authenticated = self.backend.authenticate(
            None,
            username="inactiveuser",
            password=self.password,
        )

        self.assertIsNone(authenticated)

    def test_duplicate_case_variants_fail_closed(self):
        users = get_user_model().objects
        users.create_user(username="Duplicate", password=self.password)
        users.create_user(username="duplicate", password=self.password)

        authenticated = self.backend.authenticate(
            None,
            username="DUPLICATE",
            password=self.password,
        )

        self.assertIsNone(authenticated)
