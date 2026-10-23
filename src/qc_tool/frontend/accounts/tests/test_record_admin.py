"""Account record administration uses scoped services and the maintenance gate."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from qc_tool.frontend.accounts.admin import records
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import PersonalAccessToken, UserProductGrant
from qc_tool.frontend.dashboard.models import Product, ProductRelease, ProductReleaseDefinition, QcDefinition
from qc_tool.frontend.dashboard.services import maintenance


class AccountRecordAdminTests(TestCase):
    def setUp(self):
        directory = Path(self.enterContext(TemporaryDirectory(prefix="qc-account-record-admin-")))
        self.enterContext(override_settings(
            QC_TOOL_MAINTENANCE_DIR=directory / "maintenance",
            QC_TOOL_TRANSFER_DIR=directory / "transfers", MAINTENANCE_MODE=False,
        ))
        User = get_user_model()
        self.operator = User.objects.create_user("record-admin", "operator@example.test")
        self.operator.groups.add(Group.objects.get(name=Role.ADMIN.value))
        self.operator.refresh_from_db()
        self.owner = User.objects.create_user("record-owner", "owner@example.test")
        self.other = User.objects.create_user("other-owner", "other@example.test")
        self.client.force_login(self.operator)
        for index in (1, 2):
            product = Product.objects.create(ident=f"record-product-{index}", name=f"Product {index}")
            release = ProductRelease.objects.create(product=product, release_key=f"record-release-{index}",
                revision=1, description="Admin fixture", catalog_digest=str(index) * 64, is_current=True)
            definition = QcDefinition.objects.create(product_ident=f"record-definition-{index}",
                digest=str(index) * 64, description="Admin fixture", document={}, source_path="test:admin")
            ProductReleaseDefinition.objects.create(product_release=release, qc_definition=definition, is_primary=True)
        self.grant_add = reverse("admin:accounts_userproductgrant_add")
        self.grant_list = reverse("admin:accounts_userproductgrant_changelist")
        self.token_list = reverse("admin:accounts_personalaccesstoken_changelist")

    def make_grant(self):
        return UserProductGrant.objects.create(user=self.owner, product_ident="record-product-1", created_by=self.operator)

    def make_token(self, owner=None, name="Retained token"):
        return PersonalAccessToken.objects.create(user=owner or self.owner, name=name,
            secret_digest="sha256$" + ("a" if owner is None else "b") * 64,
            token_hint="qct_fixture", permission_snapshot=["upload_delivery"], role_snapshot=["default"],
            product_idents_snapshot=["record-product-1"], is_administrator_snapshot=False)

    def test_admin_role_creates_a_validated_grant_with_actor_evidence(self):
        self.assertFalse(self.operator.is_superuser)
        with patch.object(records, "save_product_grant", wraps=records.save_product_grant) as save:
            response = self.client.post(self.grant_add, {"user": self.owner.pk, "product_ident": "record-product-1"})
        self.assertEqual(response.status_code, 302)
        grant = UserProductGrant.objects.get()
        self.assertEqual((grant.user_id, grant.product_ident, grant.created_by_id),
                         (self.owner.pk, "record-product-1", self.operator.pk))
        self.assertEqual(save.call_args.kwargs, {"created_by": self.operator})

    def test_invalid_or_duplicate_grants_are_rejected_without_writes(self):
        original = self.make_grant()
        for product in ("not-in-the-catalog", original.product_ident):
            with self.subTest(product=product):
                response = self.client.post(self.grant_add, {"user": self.owner.pk, "product_ident": product})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["adminform"].form.errors)
        self.assertEqual(UserProductGrant.objects.count(), 1)

    def test_grant_scope_can_change_but_owner_and_creator_cannot_be_forged(self):
        grant = self.make_grant()
        created_at = grant.created_at
        url = reverse("admin:accounts_userproductgrant_change", args=(grant.pk,))
        response = self.client.post(url, {"user": self.other.pk, "product_ident": "record-product-2",
                                        "created_by": self.other.pk, "created_at": "2000-01-01"})
        self.assertEqual(response.status_code, 302)
        grant.refresh_from_db()
        self.assertEqual((grant.user_id, grant.created_by_id, grant.created_at),
                         (self.owner.pk, self.operator.pk, created_at))
        self.assertEqual(grant.product_ident, "record-product-2")

    def test_grant_deletion_requires_confirmation_and_keeps_the_account(self):
        grant = self.make_grant()
        url = reverse("admin:accounts_userproductgrant_delete", args=(grant.pk,))
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertTrue(UserProductGrant.objects.filter(pk=grant.pk).exists())
        self.assertEqual(self.client.post(url, {"post": "yes"}).status_code, 302)
        self.assertFalse(UserProductGrant.objects.filter(pk=grant.pk).exists())
        self.assertTrue(get_user_model().objects.filter(pk=self.owner.pk).exists())

    def test_token_metadata_never_loads_or_displays_the_digest(self):
        token = self.make_token()
        model_admin = admin.site._registry[PersonalAccessToken]
        response = self.client.get(reverse("admin:accounts_personalaccesstoken_change", args=(token.pk,)))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Retained token")
        self.assertContains(response, "upload_delivery")
        self.assertNotContains(response, token.secret_digest)
        self.assertNotContains(response, "secret_digest")
        self.assertIn("secret_digest", model_admin.get_queryset(response.wsgi_request).get(pk=token.pk).get_deferred_fields())
        self.assertEqual(model_admin.get_actions(response.wsgi_request), {})

    def test_token_creation_and_captured_access_edits_are_forbidden(self):
        token = self.make_token()
        before = PersonalAccessToken.objects.values().get(pk=token.pk)
        change = reverse("admin:accounts_personalaccesstoken_change", args=(token.pk,))
        add = reverse("admin:accounts_personalaccesstoken_add")
        for method, url, data in (("get", add, {}), ("post", add, {"user": self.owner.pk}),
                                 ("post", change, {"name": "Forged", "user": self.other.pk,
                                     "permission_snapshot": '["manage_configuration"]',
                                     "is_administrator_snapshot": "on", "secret_digest": "forged"})):
            with self.subTest(method=method, url=url):
                self.assertEqual(getattr(self.client, method)(url, data).status_code, 403)
        self.assertEqual(PersonalAccessToken.objects.values().get(pk=token.pk), before)

    def test_token_revoke_confirms_and_calls_the_owner_service_for_exactly_one_token(self):
        token = self.make_token()
        retained = self.make_token(self.other, "Another token")
        url = reverse("admin:accounts_personalaccesstoken_delete", args=(token.pk,))
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, token.secret_digest)
        self.assertTrue(PersonalAccessToken.objects.filter(pk=token.pk).exists())
        with patch.object(records, "delete_personal_access_token", wraps=records.delete_personal_access_token) as revoke:
            self.assertEqual(self.client.post(url, {"post": "yes"}).status_code, 302)
        revoke.assert_called_once_with(self.owner, token.pk)
        self.assertFalse(PersonalAccessToken.objects.filter(pk=token.pk).exists())
        self.assertTrue(PersonalAccessToken.objects.filter(pk=retained.pk).exists())

    def test_non_admin_staff_and_product_managers_cannot_manage_account_records(self):
        grant, token = self.make_grant(), self.make_token()
        staff = get_user_model().objects.create_user("generic-staff")
        staff.user_permissions.add(*Permission.objects.filter(content_type__app_label="accounts"))
        get_user_model().objects.filter(pk=staff.pk).update(is_staff=True)
        staff.refresh_from_db()
        manager = get_user_model().objects.create_user("product-manager")
        manager.groups.add(Group.objects.get(name=Role.PRODUCT_MANAGER.value))
        manager.refresh_from_db()
        routes = (self.grant_list, self.grant_add,
            reverse("admin:accounts_userproductgrant_change", args=(grant.pk,)),
            reverse("admin:accounts_userproductgrant_delete", args=(grant.pk,)), self.token_list,
            reverse("admin:accounts_personalaccesstoken_change", args=(token.pk,)),
            reverse("admin:accounts_personalaccesstoken_delete", args=(token.pk,)))
        for user in (staff, manager):
            self.client.force_login(user)
            for url in routes:
                with self.subTest(user=user.username, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(self.grant_add,
                {"user": self.owner.pk, "product_ident": "record-product-2"}).status_code, 403)
            self.assertEqual(self.client.post(reverse("admin:accounts_personalaccesstoken_delete", args=(token.pk,)),
                                              {"post": "yes"}).status_code, 403)
        self.assertTrue(UserProductGrant.objects.filter(pk=grant.pk).exists())
        self.assertTrue(PersonalAccessToken.objects.filter(pk=token.pk).exists())

    def test_maintenance_keeps_metadata_readable_and_blocks_every_record_mutation(self):
        grant, token = self.make_grant(), self.make_token()
        generation = maintenance.enable(self.operator, 0)["generation"]
        self.assertEqual(maintenance.advance(generation)["phase"], "ready")
        for url in (self.grant_list, self.token_list):
            self.assertEqual(self.client.get(url).status_code, 200)
        for url, data in ((self.grant_add, {"user": self.other.pk, "product_ident": "record-product-2"}),
                         (reverse("admin:accounts_userproductgrant_change", args=(grant.pk,)), {"product_ident": "record-product-2"}),
                         (reverse("admin:accounts_userproductgrant_delete", args=(grant.pk,)), {"post": "yes"}),
                         (reverse("admin:accounts_personalaccesstoken_delete", args=(token.pk,)), {"post": "yes"})):
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, data).status_code, 503)
        grant.refresh_from_db()
        self.assertEqual(grant.product_ident, "record-product-1")
        self.assertEqual(UserProductGrant.objects.count(), 1)
        self.assertTrue(PersonalAccessToken.objects.filter(pk=token.pk).exists())
