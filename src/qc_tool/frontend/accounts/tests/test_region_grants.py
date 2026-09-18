from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import IntegrityError
from django.db import transaction
from django.test import TestCase

from qc_tool.frontend.accounts.authorization.access import access_for
from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.accounts.models import UserRegionGrant
from qc_tool.frontend.accounts.services.role_permissions import (
    capability_content_type,
)


class UserRegionGrantTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="region-user")
        permissions = Permission.objects.filter(
            content_type=capability_content_type(),
            codename__in={
                AccountPermission.VIEW_REGION_DELIVERIES.value,
                AccountPermission.VIEW_REGION_AGGREGATE_REPORT.value,
            },
        )
        self.user.user_permissions.add(*permissions)

    def test_multiple_grants_are_exposed_as_exact_opaque_codes(self):
        codes = {"CZ-001", "cz-001", " product unit 42 "}
        UserRegionGrant.objects.bulk_create(
            [
                UserRegionGrant(user=self.user, region_code=code)
                for code in codes
            ]
        )

        access = access_for(self.user)

        self.assertEqual(access.region_codes, frozenset(codes))
        self.assertTrue(access.can_view_region_deliveries)
        self.assertTrue(access.can_view_region_aggregate_report)

    def test_same_code_is_unique_per_user_but_reusable_by_another_user(self):
        other_user = get_user_model().objects.create_user(username="other-user")
        UserRegionGrant.objects.create(user=self.user, region_code="CZ-001")
        UserRegionGrant.objects.create(user=other_user, region_code="CZ-001")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UserRegionGrant.objects.create(
                    user=self.user,
                    region_code="CZ-001",
                )

    def test_created_by_is_optional_and_nulls_when_creator_is_deleted(self):
        creator = get_user_model().objects.create_user(username="grant-admin")
        grant = UserRegionGrant.objects.create(
            user=self.user,
            region_code="CZ-001",
            created_by=creator,
        )

        creator.delete()
        grant.refresh_from_db()

        self.assertIsNone(grant.created_by)

    def test_empty_code_is_rejected_by_the_database(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UserRegionGrant.objects.create(user=self.user, region_code="")
