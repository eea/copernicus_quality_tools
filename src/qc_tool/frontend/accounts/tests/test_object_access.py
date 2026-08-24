from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from qc_tool.frontend.accounts.authorization.access import AccountAccess
from qc_tool.frontend.accounts.authorization.access import access_for
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.accounts.models import UserRegionGrant
from qc_tool.frontend.accounts.models import UserProfile
from qc_tool.frontend.dashboard.access import can_view_delivery
from qc_tool.frontend.dashboard.access import can_view_job
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.dashboard.views import query_deliveries


class DashboardObjectAccessTests(TestCase):
    def setUp(self):
        self.owner = self.create_user("owner", country="CZ")
        self.other = self.create_user("other", country="SK")
        self.delivery = self.create_delivery(
            self.owner,
            filename="delivery.zip",
            product_ident="clc2024",
        )
        self.job = Job.objects.create(
            delivery=self.delivery,
            product_ident="clc2024",
            product_description="Corine Land Cover",
        )

    def create_user(
        self,
        username,
        *,
        role=None,
        country=None,
        region_codes=(),
        product_idents=(),
        is_superuser=False,
    ):
        user = get_user_model().objects.create_user(
            username=username,
            is_staff=is_superuser,
            is_superuser=is_superuser,
        )
        if role is not None:
            group, _created = Group.objects.get_or_create(name=role.value)
            user.groups.add(group)
        if country is not None:
            UserProfile.objects.create(
                user=user,
                country=country,
            )
        UserRegionGrant.objects.bulk_create(
            [
                UserRegionGrant(user=user, aoi_code=region_code)
                for region_code in region_codes
            ]
        )
        UserProductGrant.objects.bulk_create(
            [
                UserProductGrant(user=user, product_ident=product_ident)
                for product_ident in product_idents
            ]
        )
        return user

    def create_delivery(self, user, *, filename, product_ident):
        return Delivery.objects.create(
            user=user,
            filename=filename,
            size_bytes=1,
            product_ident=product_ident,
            product_description=product_ident,
        )

    def grant_capability(self, user, codename):
        permission = Permission.objects.get(
            content_type__app_label="accounts",
            codename=codename,
        )
        user.user_permissions.add(permission)

    def protected_urls(self):
        return (
            reverse("job_history_json", args=[self.delivery.pk]),
            reverse("job_history", args=[self.delivery.pk]),
            reverse("show_result", args=[self.job.pk]),
            reverse("job_report_pdf", args=[self.job.pk]),
            reverse("job_report_json", args=[self.job.pk]),
            reverse("job_combined_log", args=[self.job.pk]),
            reverse("download_delivery_file", args=[self.delivery.pk]),
            reverse("get_attachment", args=[self.job.pk, "details.txt"]),
            reverse("update_job", args=[self.job.pk]),
        )

    def test_anonymous_users_are_redirected_from_every_object_read(self):
        for url in self.protected_urls():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn("/accounts/login/", response.url)

    def test_cross_owner_is_denied_before_artifacts_are_read(self):
        self.client.force_login(self.other)

        for url in self.protected_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_owner_managers_and_superuser_can_read_job(self):
        allowed_users = (
            self.owner,
            self.create_user(
                "region-manager",
                role=Role.REGION_MANAGER,
                region_codes=("CZ",),
            ),
            self.create_user(
                "product-manager",
                role=Role.PRODUCT_MANAGER,
                product_idents=("clc2024",),
            ),
            self.create_user("superuser", is_superuser=True),
        )

        for user in allowed_users:
            with self.subTest(username=user.username):
                self.client.force_login(user)
                response = self.client.get(
                    reverse("update_job", args=[self.job.pk])
                )
                self.assertEqual(response.status_code, 200)
                self.client.logout()

    def test_policy_scopes_region_and_product_roles(self):
        region_manager = self.create_user(
            "scoped-region-manager",
            role=Role.REGION_MANAGER,
            region_codes=("CZ", "DE"),
        )
        product_manager = self.create_user(
            "scoped-product-manager",
            role=Role.PRODUCT_MANAGER,
            product_idents=("clc2024", "clc2018"),
        )
        outside_delivery = self.create_delivery(
            self.other,
            filename="outside.zip",
            product_ident="urban",
        )
        german_owner = self.create_user("german-owner", country="DE")
        second_region_delivery = self.create_delivery(
            german_owner,
            filename="second-region.zip",
            product_ident="urban",
        )
        second_product_delivery = self.create_delivery(
            self.other,
            filename="second-product.zip",
            product_ident="CLC2018",
        )

        self.assertFalse(
            can_view_delivery(AccountAccess.anonymous(), self.delivery)
        )
        self.assertTrue(can_view_delivery(access_for(self.owner), self.delivery))
        self.assertFalse(can_view_delivery(access_for(self.other), self.delivery))
        self.assertTrue(
            can_view_delivery(access_for(region_manager), self.delivery)
        )
        self.assertTrue(
            can_view_delivery(
                access_for(region_manager),
                second_region_delivery,
            )
        )
        self.assertFalse(
            can_view_delivery(access_for(region_manager), outside_delivery)
        )
        self.assertTrue(can_view_job(access_for(product_manager), self.job))
        self.assertTrue(
            can_view_delivery(
                access_for(product_manager),
                second_product_delivery,
            )
        )
        self.assertFalse(
            can_view_delivery(access_for(product_manager), outside_delivery)
        )

        _total, rows = query_deliveries(region_manager, limit=100)
        visible_ids = {row["id"] for row in rows}
        self.assertIn(self.delivery.pk, visible_ids)
        self.assertIn(second_region_delivery.pk, visible_ids)
        self.assertNotIn(outside_delivery.pk, visible_ids)

        _total, rows = query_deliveries(product_manager, limit=100)
        visible_ids = {row["id"] for row in rows}
        self.assertIn(self.delivery.pk, visible_ids)
        self.assertIn(second_product_delivery.pk, visible_ids)
        self.assertNotIn(outside_delivery.pk, visible_ids)

    def test_direct_region_permission_and_grant_scope_a_default_user(self):
        unprivileged = self.create_user(
            "unprivileged-region-user",
            role=Role.DEFAULT,
            region_codes=("CZ",),
        )
        directly_privileged = self.create_user(
            "direct-region-user",
            role=Role.DEFAULT,
            region_codes=("CZ",),
        )
        permission_without_grant = self.create_user(
            "region-permission-without-grant",
            role=Role.DEFAULT,
        )
        self.grant_capability(
            directly_privileged,
            "view_region_deliveries",
        )
        self.grant_capability(
            permission_without_grant,
            "view_region_deliveries",
        )

        self.assertFalse(
            can_view_delivery(access_for(unprivileged), self.delivery)
        )
        self.assertTrue(
            can_view_delivery(access_for(directly_privileged), self.delivery)
        )
        self.assertFalse(
            can_view_delivery(
                access_for(permission_without_grant),
                self.delivery,
            )
        )

    def test_direct_product_permission_scopes_a_default_user(self):
        unprivileged = self.create_user(
            "unprivileged-product-user",
            role=Role.DEFAULT,
            product_idents=("clc2024",),
        )
        directly_privileged = self.create_user(
            "direct-product-user",
            role=Role.DEFAULT,
            product_idents=("clc2024",),
        )
        permission_without_grant = self.create_user(
            "product-permission-without-grant",
            role=Role.DEFAULT,
        )
        self.grant_capability(
            directly_privileged,
            "view_product_deliveries",
        )
        self.grant_capability(
            permission_without_grant,
            "view_product_deliveries",
        )

        self.assertFalse(
            can_view_delivery(access_for(unprivileged), self.delivery)
        )
        self.assertTrue(
            can_view_delivery(access_for(directly_privileged), self.delivery)
        )
        self.assertFalse(
            can_view_delivery(
                access_for(permission_without_grant),
                self.delivery,
            )
        )

    def test_direct_region_and_product_permissions_are_additive(self):
        scoped_user = self.create_user(
            "direct-combined-user",
            role=Role.DEFAULT,
            region_codes=("CZ",),
            product_idents=("clc2024",),
        )
        self.grant_capability(scoped_user, "view_region_deliveries")
        self.grant_capability(scoped_user, "view_product_deliveries")
        region_delivery = self.create_delivery(
            self.owner,
            filename="region-scope.zip",
            product_ident="urban",
        )
        product_delivery = self.create_delivery(
            self.other,
            filename="product-scope.zip",
            product_ident="CLC2024",
        )
        outside_delivery = self.create_delivery(
            self.other,
            filename="outside-combined-scope.zip",
            product_ident="urban",
        )

        access = access_for(scoped_user)
        self.assertTrue(can_view_delivery(access, region_delivery))
        self.assertTrue(can_view_delivery(access, product_delivery))
        self.assertFalse(can_view_delivery(access, outside_delivery))

        _total, rows = query_deliveries(scoped_user, limit=100)
        visible_ids = {row["id"] for row in rows}
        self.assertIn(region_delivery.pk, visible_ids)
        self.assertIn(product_delivery.pk, visible_ids)
        self.assertNotIn(outside_delivery.pk, visible_ids)
