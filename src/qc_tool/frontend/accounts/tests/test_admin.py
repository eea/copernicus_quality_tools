from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory
from django.test import SimpleTestCase
from django.test import TestCase
from django.urls import reverse

from qc_tool.frontend.accounts.admin.role_permissions import synchronize_admin_role
from qc_tool.frontend.accounts.admin.users import PersonalAccessTokenInline
from qc_tool.frontend.accounts.authorization.access import access_for
from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import AccountCapability
from qc_tool.frontend.accounts.models import PersonalAccessToken
from qc_tool.frontend.accounts.models import UserProfile
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.accounts.models import UserRegionGrant
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.dashboard.models import S3Info


class AccountAdminRegistrationTests(SimpleTestCase):
    def test_autodiscovery_composes_accounts_without_hiding_domain_models(self):
        user_admin = admin.site._registry[get_user_model()]
        group_admin = admin.site._registry[Group]

        self.assertEqual(user_admin.__class__.__name__, "AccountUserAdmin")
        self.assertEqual(
            user_admin.__class__.__module__,
            "qc_tool.frontend.accounts.admin.users",
        )
        self.assertEqual(
            tuple(inline.model for inline in user_admin.inlines),
            (
                PersonalAccessToken,
                UserProfile,
                UserRegionGrant,
                UserProductGrant,
            ),
        )
        self.assertEqual(group_admin.__class__.__name__, "AccountGroupAdmin")
        for model in (Delivery, Job, S3Info):
            with self.subTest(model=model):
                self.assertTrue(admin.site.is_registered(model))


class AccountAdminConfigurationTests(SimpleTestCase):
    def test_user_list_exposes_roles_and_profile_scope(self):
        user_admin = admin.site._registry[get_user_model()]

        self.assertIn("role_names", user_admin.list_display)
        self.assertIn("direct_qc_permissions", user_admin.list_display)
        self.assertIn("region_codes", user_admin.list_display)
        self.assertIn("product_idents", user_admin.list_display)
        self.assertIn("profile_country", user_admin.list_display)
        self.assertIn("profile_product_family", user_admin.list_display)
        self.assertIn("groups", user_admin.filter_horizontal)
        self.assertIn("user_permissions", user_admin.filter_horizontal)
        self.assertIn(
            ("region_grants__aoi_code", admin.AllValuesFieldListFilter),
            user_admin.list_filter,
        )
        self.assertIn(
            "region_grants__aoi_code__exact",
            user_admin.search_fields,
        )
        self.assertIn(
            ("product_grants__product_ident", admin.AllValuesFieldListFilter),
            user_admin.list_filter,
        )
        self.assertIn(
            "product_grants__product_ident__exact",
            user_admin.search_fields,
        )
        self.assertEqual(
            user_admin.profile_country.short_description,
            "Legacy delivery region",
        )
        self.assertEqual(
            user_admin.profile_product_family.short_description,
            "Legacy product family",
        )

    def test_api_inline_never_exposes_or_edits_the_stored_digest(self):
        inline = PersonalAccessTokenInline(get_user_model(), admin.site)

        self.assertEqual(
            inline.fields,
            ("name", "token_hint", "created_at", "last_used_at"),
        )
        self.assertEqual(inline.readonly_fields, inline.fields)
        self.assertIn("secret_digest", inline.exclude)
        self.assertIn("permission_snapshot", inline.exclude)
        self.assertTrue(inline.can_delete)
        self.assertEqual(inline.extra, 0)
        self.assertFalse(inline.has_add_permission(RequestFactory().get("/")))


class AdminRoleTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.user_admin = admin.site._registry[self.user_model]
        self.request = RequestFactory().get("/admin/auth/user/")
        self.request.user = self.user_model.objects.create_superuser(
            username="root-admin",
            email="root@example.test",
            password="password",
        )
        self.admin_group = synchronize_admin_role()

    def test_admin_role_grants_account_management_permissions(self):
        expected_permissions = {
            (model._meta.app_label, f"{action}_{model._meta.model_name}")
            for model in (
                self.user_model,
                Group,
                UserProfile,
                PersonalAccessToken,
                UserRegionGrant,
                UserProductGrant,
            )
            for action in ("add", "change", "delete", "view")
            if not (model is self.user_model and action == "delete")
        }
        granted_permissions = set(
            self.admin_group.permissions.values_list(
                "content_type__app_label",
                "codename",
            )
        )

        self.assertTrue(expected_permissions.issubset(granted_permissions))
        self.assertNotIn(
            (self.user_model._meta.app_label, "delete_user"),
            granted_permissions,
        )

    def test_user_deletion_is_unavailable_in_admin(self):
        target = self.user_model.objects.create_user(username="retained-user")
        Delivery.objects.create(
            user=target,
            filename="retained.zip",
            size_bytes=1,
        )

        self.assertFalse(self.user_admin.has_delete_permission(self.request))
        self.assertFalse(
            self.user_admin.has_delete_permission(self.request, target)
        )

    def test_admin_membership_controls_staff_access(self):
        user = self.user_model.objects.create_user(
            username="role-admin",
            password="password",
        )

        user.groups.add(self.admin_group)
        user.refresh_from_db()
        self.assertTrue(user.is_staff)
        self.assertTrue(user.has_perm("auth.change_user"))
        self.assertTrue(user.has_perm("auth.change_group"))
        self.assertTrue(user.has_perm("accounts.change_userprofile"))
        self.assertTrue(user.has_perm("accounts.change_personalaccesstoken"))
        self.assertFalse(user.has_perm("dashboard.change_userprofile"))
        self.assertFalse(user.has_perm("dashboard.change_personalaccesstoken"))
        self.assertTrue(user.has_perm("accounts.change_userregiongrant"))
        self.assertTrue(user.has_perm("accounts.change_userproductgrant"))

        user.groups.remove(self.admin_group)
        user.refresh_from_db()
        self.assertFalse(user.is_staff)

    def test_admin_role_can_open_user_and_group_management(self):
        user = self.user_model.objects.create_user(
            username="site-admin",
            password="password",
        )
        user.groups.add(self.admin_group)
        self.client.force_login(user)

        for route_name in ("admin:auth_user_changelist", "admin:auth_group_changelist"):
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)

    def test_synchronization_repairs_existing_admin_members(self):
        user = self.user_model.objects.create_user(
            username="existing-role-admin",
            password="password",
        )
        user.groups.add(self.admin_group)
        self.user_model.objects.filter(pk=user.pk).update(is_staff=False)

        synchronize_admin_role()

        user.refresh_from_db()
        self.assertTrue(user.is_staff)

    def test_removing_admin_role_does_not_disable_superuser_staff(self):
        user = self.user_model.objects.create_superuser(
            username="superuser",
            email="superuser@example.test",
            password="password",
        )
        user.groups.add(self.admin_group)

        user.groups.remove(self.admin_group)

        user.refresh_from_db()
        self.assertTrue(user.is_staff)

    def test_role_picker_only_offers_canonical_groups(self):
        Group.objects.create(name="legacy-group")
        Group.objects.get_or_create(name="region_manager")
        groups_field = self.user_model._meta.get_field("groups")

        form_field = self.user_admin.formfield_for_manytomany(
            groups_field,
            self.request,
        )

        self.assertEqual(
            set(form_field.queryset.values_list("name", flat=True)),
            set(Role.values()),
        )
        self.assertNotIn(
            "region_manager",
            form_field.queryset.values_list("name", flat=True),
        )

    def test_permission_picker_only_offers_qc_capabilities(self):
        permissions_field = self.user_model._meta.get_field("user_permissions")
        unrelated = Permission.objects.get(
            content_type__app_label="auth",
            codename="change_group",
        )

        form_field = self.user_admin.formfield_for_manytomany(
            permissions_field,
            self.request,
        )
        offered = form_field.queryset

        capability_content_type = ContentType.objects.get_for_model(
            AccountCapability,
            for_concrete_model=False,
        )
        self.assertEqual(
            set(offered.values_list("content_type_id", flat=True)),
            {capability_content_type.pk},
        )
        self.assertEqual(
            set(offered.values_list("codename", flat=True)),
            {permission.value for permission in AccountPermission},
        )
        self.assertTrue(
            {
                AccountPermission.VIEW_REGION_DELIVERIES.value,
                AccountPermission.VIEW_REGION_AGGREGATE_REPORT.value,
            }.issubset(set(offered.values_list("codename", flat=True)))
        )
        self.assertNotIn(unrelated, offered)

    def test_non_super_admin_form_can_assign_only_qc_permissions(self):
        group_admin = self.user_model.objects.create_user(
            username="permission-admin",
            password="password",
        )
        group_admin.groups.add(self.admin_group)
        target = self.user_model.objects.create_user(
            username="permission-target",
            password="password",
        )
        request = RequestFactory().get("/admin/auth/user/")
        request.user = group_admin
        form_class = self.user_admin.get_form(request, target)
        qc_permission = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(
                AccountCapability,
                for_concrete_model=False,
            ),
            codename=AccountPermission.RUN_QC.value,
        )
        unrelated = Permission.objects.get(
            content_type__app_label="auth",
            codename="change_group",
        )
        base_data = {
            "username": target.username,
            "first_name": "",
            "last_name": "",
            "email": "",
            "is_active": "on",
            "groups": [
                str(group.pk)
                for group in target.groups.filter(name__in=Role.values())
            ],
        }

        allowed_form = form_class(
            data={**base_data, "user_permissions": [str(qc_permission.pk)]},
            instance=target,
        )
        rejected_form = form_class(
            data={**base_data, "user_permissions": [str(unrelated.pk)]},
            instance=target,
        )

        self.assertTrue(allowed_form.is_valid(), allowed_form.errors)
        self.assertFalse(rejected_form.is_valid())
        self.assertIn("user_permissions", rejected_form.errors)

    def test_add_form_exposes_roles_and_additional_qc_permissions(self):
        form_class = self.user_admin.get_form(self.request, obj=None)

        self.assertIn("groups", form_class.base_fields)
        self.assertIn("user_permissions", form_class.base_fields)
        self.assertEqual(form_class.base_fields["groups"].label, "Roles")
        self.assertEqual(
            form_class.base_fields["user_permissions"].label,
            "Additional QC permissions",
        )

    def test_admin_add_view_assigns_role_and_direct_qc_permission(self):
        group_admin = self.user_model.objects.create_user(
            username="add-view-admin",
            password="password",
        )
        group_admin.groups.add(self.admin_group)
        product_manager = Group.objects.get(name=Role.PRODUCT_MANAGER.value)
        qc_permission = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(
                AccountCapability,
                for_concrete_model=False,
            ),
            codename=AccountPermission.RUN_QC.value,
        )
        self.client.force_login(group_admin)
        url = reverse("admin:auth_user_add")

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Additional QC permissions")

        response = self.client.post(
            url,
            {
                "username": "admin-created-user",
                "password1": "sufficient-password",
                "password2": "sufficient-password",
                "groups": [str(product_manager.pk)],
                "user_permissions": [str(qc_permission.pk)],
                "personal_access_tokens-TOTAL_FORMS": "0",
                "personal_access_tokens-INITIAL_FORMS": "0",
                "personal_access_tokens-MIN_NUM_FORMS": "0",
                "personal_access_tokens-MAX_NUM_FORMS": "0",
                "userprofile-TOTAL_FORMS": "1",
                "userprofile-INITIAL_FORMS": "0",
                "userprofile-MIN_NUM_FORMS": "0",
                "userprofile-MAX_NUM_FORMS": "1",
                "region_grants-TOTAL_FORMS": "1",
                "region_grants-INITIAL_FORMS": "0",
                "region_grants-MIN_NUM_FORMS": "0",
                "region_grants-MAX_NUM_FORMS": "1000",
                "product_grants-TOTAL_FORMS": "1",
                "product_grants-INITIAL_FORMS": "0",
                "product_grants-MIN_NUM_FORMS": "0",
                "product_grants-MAX_NUM_FORMS": "1000",
                "_save": "Save",
            },
        )

        self.assertEqual(response.status_code, 302)
        created = self.user_model.objects.get(username="admin-created-user")
        self.assertEqual(
            set(created.groups.values_list("name", flat=True)),
            {Role.DEFAULT.value, Role.PRODUCT_MANAGER.value},
        )
        self.assertEqual(
            set(created.user_permissions.values_list("codename", flat=True)),
            {AccountPermission.RUN_QC.value},
        )

    def test_admin_user_page_shows_status_without_rendering_digest(self):
        target = self.user_model.objects.create_user(username="api-target")
        stored_digest = "sha256$" + ("b" * 64)
        PersonalAccessToken.objects.create(
            user=target,
            name="Admin-visible token",
            secret_digest=stored_digest,
            token_hint="qct_example…",
        )
        self.client.force_login(self.request.user)

        response = self.client.get(
            reverse("admin:auth_user_change", args=(target.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Admin-visible token")
        self.assertContains(response, "qct_example")
        self.assertNotContains(response, stored_digest)

    def test_canonical_groups_cannot_be_renamed_or_deleted_in_admin(self):
        group_admin = admin.site._registry[Group]
        extra_group = Group.objects.create(name="extra-group")

        self.assertEqual(
            group_admin.get_readonly_fields(self.request, self.admin_group),
            ("name",),
        )
        canonical_fields = {
            field
            for _title, options in group_admin.get_fieldsets(
                self.request,
                self.admin_group,
            )
            for field in options["fields"]
        }
        self.assertEqual(canonical_fields, {"name"})
        self.assertFalse(
            group_admin.has_delete_permission(self.request, self.admin_group),
        )
        self.assertTrue(
            group_admin.has_delete_permission(self.request, extra_group),
        )

        self.admin_group.name = "renamed-admin"
        group_admin.save_model(
            self.request,
            self.admin_group,
            form=None,
            change=True,
        )
        self.admin_group.refresh_from_db()
        self.assertEqual(self.admin_group.name, Role.ADMIN.value)

        group_admin.delete_queryset(
            self.request,
            Group.objects.filter(pk__in=(self.admin_group.pk, extra_group.pk)),
        )

        self.assertTrue(Group.objects.filter(pk=self.admin_group.pk).exists())
        self.assertFalse(Group.objects.filter(pk=extra_group.pk).exists())

    def test_role_synchronization_restores_all_canonical_groups(self):
        Group.objects.filter(name=Role.PRODUCT_MANAGER.value).delete()

        synchronize_admin_role()

        self.assertEqual(
            set(
                Group.objects.filter(name__in=Role.values()).values_list(
                    "name",
                    flat=True,
                )
            ),
            set(Role.values()),
        )

    def test_group_admin_cannot_escalate_to_superuser(self):
        group_admin = self.user_model.objects.create_user(
            username="limited-admin",
            password="password",
        )
        group_admin.groups.add(self.admin_group)
        superuser = self.user_model.objects.create_superuser(
            username="protected-superuser",
            email="protected@example.test",
            password="password",
        )
        request = RequestFactory().get("/admin/auth/user/")
        request.user = group_admin

        field_names = {
            field
            for _title, options in self.user_admin.get_fieldsets(
                request,
                group_admin,
            )
            for field in options["fields"]
        }

        self.assertNotIn("is_superuser", field_names)
        self.assertFalse(
            self.user_admin.has_change_permission(request, superuser),
        )

    def test_list_columns_render_roles_and_profile(self):
        user = self.user_model.objects.create_user(
            username="scoped-user",
            password="password",
        )
        product_manager = Group.objects.get(name=Role.PRODUCT_MANAGER.value)
        user.groups.add(product_manager)
        UserProfile.objects.create(
            user=user,
            country="CZ",
            product_family="HRL",
        )
        user.user_permissions.add(
            Permission.objects.get(
                content_type=ContentType.objects.get_for_model(
                    AccountCapability,
                    for_concrete_model=False,
                ),
                codename=AccountPermission.RUN_QC.value,
            )
        )
        user = self.user_admin.get_queryset(self.request).get(pk=user.pk)

        self.assertEqual(
            self.user_admin.role_names(user),
            "Default, Product Manager",
        )
        self.assertEqual(self.user_admin.profile_country(user), "CZ")
        self.assertEqual(self.user_admin.profile_product_family(user), "HRL")
        self.assertEqual(
            self.user_admin.direct_qc_permissions(user),
            "Can run quality control",
        )


class RegionGrantAdminTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.user_admin = admin.site._registry[self.user_model]
        self.actor = self.user_model.objects.create_user(
            username="region-grant-admin",
            password="password",
        )
        self.actor.groups.add(synchronize_admin_role())
        self.client.force_login(self.actor)

    def inline_management_data(self, *, region_total, region_initial):
        return {
            "personal_access_tokens-TOTAL_FORMS": "0",
            "personal_access_tokens-INITIAL_FORMS": "0",
            "personal_access_tokens-MIN_NUM_FORMS": "0",
            "personal_access_tokens-MAX_NUM_FORMS": "0",
            "userprofile-TOTAL_FORMS": "1",
            "userprofile-INITIAL_FORMS": "0",
            "userprofile-MIN_NUM_FORMS": "0",
            "userprofile-MAX_NUM_FORMS": "1",
            "region_grants-TOTAL_FORMS": str(region_total),
            "region_grants-INITIAL_FORMS": str(region_initial),
            "region_grants-MIN_NUM_FORMS": "0",
            "region_grants-MAX_NUM_FORMS": "1000",
            "product_grants-TOTAL_FORMS": "1",
            "product_grants-INITIAL_FORMS": "0",
            "product_grants-MIN_NUM_FORMS": "0",
            "product_grants-MAX_NUM_FORMS": "1000",
        }

    def test_add_view_creates_multiple_exact_grants_with_audit_creator(self):
        region_permissions = Permission.objects.filter(
            content_type=ContentType.objects.get_for_model(
                AccountCapability,
                for_concrete_model=False,
            ),
            codename__in={
                AccountPermission.VIEW_REGION_DELIVERIES.value,
                AccountPermission.VIEW_REGION_AGGREGATE_REPORT.value,
            },
        )
        url = reverse("admin:auth_user_add")

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Region grants — exact AOI codes")
        self.assertContains(response, "AOI catalog PR")
        self.assertContains(response, "does not grant it")
        self.assertContains(response, "Legacy delivery region")

        response = self.client.post(
            url,
            {
                "username": "regional-user",
                "password1": "sufficient-password",
                "password2": "sufficient-password",
                "user_permissions": [
                    str(permission.pk) for permission in region_permissions
                ],
                "region_grants-0-aoi_code": "AOI-ONE",
                "region_grants-1-aoi_code": "aoi:two/2",
                **self.inline_management_data(
                    region_total=2,
                    region_initial=0,
                ),
                "_save": "Save",
            },
        )

        self.assertEqual(response.status_code, 302)
        user = self.user_model.objects.get(username="regional-user")
        self.assertEqual(
            set(user.groups.values_list("name", flat=True)),
            {Role.DEFAULT.value},
        )
        self.assertEqual(
            set(user.user_permissions.values_list("codename", flat=True)),
            {
                AccountPermission.VIEW_REGION_DELIVERIES.value,
                AccountPermission.VIEW_REGION_AGGREGATE_REPORT.value,
            },
        )
        self.assertEqual(
            list(user.region_grants.values_list("aoi_code", flat=True)),
            ["AOI-ONE", "aoi:two/2"],
        )
        self.assertEqual(
            set(user.region_grants.values_list("created_by_id", flat=True)),
            {self.actor.pk},
        )
        account_access = access_for(user)
        self.assertTrue(account_access.can_view_region_deliveries)
        self.assertTrue(account_access.can_view_region_aggregate_report)

    def test_change_view_preserves_creator_and_audits_new_grant(self):
        user = self.user_model.objects.create_user(
            username="existing-regional-user",
            password="password",
        )
        existing = UserRegionGrant.objects.create(
            user=user,
            aoi_code="AOI-EXISTING",
            created_by=user,
        )
        url = reverse("admin:auth_user_change", args=(user.pk,))

        response = self.client.post(
            url,
            {
                "username": user.username,
                "first_name": "",
                "last_name": "",
                "email": "",
                "is_active": "on",
                "groups": [
                    str(group.pk)
                    for group in user.groups.filter(name__in=Role.values())
                ],
                "region_grants-0-id": str(existing.pk),
                "region_grants-0-aoi_code": existing.aoi_code,
                "region_grants-1-aoi_code": "AOI-NEW",
                **self.inline_management_data(
                    region_total=2,
                    region_initial=1,
                ),
                "_save": "Save",
            },
        )

        self.assertEqual(response.status_code, 302)
        existing.refresh_from_db()
        added = user.region_grants.get(aoi_code="AOI-NEW")
        self.assertEqual(existing.created_by_id, user.pk)
        self.assertEqual(added.created_by_id, self.actor.pk)

    def test_region_summary_and_exact_search_use_all_grants(self):
        first = self.user_model.objects.create_user(
            username="first-region-user",
            password="password",
        )
        second = self.user_model.objects.create_user(
            username="second-region-user",
            password="password",
        )
        UserRegionGrant.objects.bulk_create(
            [
                UserRegionGrant(user=first, aoi_code="AOI-20"),
                UserRegionGrant(user=first, aoi_code="AOI-10"),
                UserRegionGrant(user=second, aoi_code="AOI-OTHER"),
            ]
        )
        request = RequestFactory().get("/admin/auth/user/")
        request.user = self.actor
        queryset = self.user_admin.get_queryset(request)
        searched, may_duplicate = self.user_admin.get_search_results(
            request,
            queryset,
            "AOI-10",
        )

        self.assertEqual(list(searched), [first])
        self.assertTrue(may_duplicate)
        listed = queryset.get(pk=first.pk)
        self.assertEqual(self.user_admin.region_codes(listed), "AOI-10, AOI-20")


class ProductGrantAdminTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.user_admin = admin.site._registry[self.user_model]
        self.actor = self.user_model.objects.create_user(
            username="product-grant-admin",
            password="password",
        )
        self.actor.groups.add(synchronize_admin_role())
        self.client.force_login(self.actor)

    def inline_management_data(self, *, product_total, product_initial):
        return {
            "personal_access_tokens-TOTAL_FORMS": "0",
            "personal_access_tokens-INITIAL_FORMS": "0",
            "personal_access_tokens-MIN_NUM_FORMS": "0",
            "personal_access_tokens-MAX_NUM_FORMS": "0",
            "userprofile-TOTAL_FORMS": "1",
            "userprofile-INITIAL_FORMS": "0",
            "userprofile-MIN_NUM_FORMS": "0",
            "userprofile-MAX_NUM_FORMS": "1",
            "region_grants-TOTAL_FORMS": "1",
            "region_grants-INITIAL_FORMS": "0",
            "region_grants-MIN_NUM_FORMS": "0",
            "region_grants-MAX_NUM_FORMS": "1000",
            "product_grants-TOTAL_FORMS": str(product_total),
            "product_grants-INITIAL_FORMS": str(product_initial),
            "product_grants-MIN_NUM_FORMS": "0",
            "product_grants-MAX_NUM_FORMS": "1000",
        }

    @patch(
        "qc_tool.frontend.accounts.services.products."
        "available_product_descriptions",
        return_value={
            "clc2024": "CORINE Land Cover 2024",
            "hrl2021": "High Resolution Layer 2021",
        },
    )
    def test_add_view_creates_multiple_validated_grants(self, _catalog):
        product_manager = Group.objects.get(name=Role.PRODUCT_MANAGER.value)
        url = reverse("admin:auth_user_add")

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "clc2024 — CORINE Land Cover 2024")
        self.assertContains(response, "Legacy product family")

        response = self.client.post(
            url,
            {
                "username": "product-user",
                "password1": "sufficient-password",
                "password2": "sufficient-password",
                "groups": [str(product_manager.pk)],
                "product_grants-0-product_ident": "clc2024",
                "product_grants-1-product_ident": "hrl2021",
                **self.inline_management_data(
                    product_total=2,
                    product_initial=0,
                ),
                "_save": "Save",
            },
        )

        self.assertEqual(response.status_code, 302)
        user = self.user_model.objects.get(username="product-user")
        self.assertEqual(
            set(user.groups.values_list("name", flat=True)),
            {Role.DEFAULT.value, Role.PRODUCT_MANAGER.value},
        )
        self.assertEqual(
            list(user.product_grants.values_list("product_ident", flat=True)),
            ["clc2024", "hrl2021"],
        )
        self.assertEqual(
            set(user.product_grants.values_list("created_by_id", flat=True)),
            {self.actor.pk},
        )

    @patch(
        "qc_tool.frontend.accounts.services.products."
        "available_product_descriptions",
        return_value={
            "clc2024": "CORINE Land Cover 2024",
            "hrl2021": "High Resolution Layer 2021",
        },
    )
    def test_change_view_preserves_creator_and_audits_new_grant(self, _catalog):
        user = self.user_model.objects.create_user(
            username="existing-product-user",
            password="password",
        )
        existing = UserProductGrant.objects.create(
            user=user,
            product_ident="clc2024",
            created_by=user,
        )
        url = reverse("admin:auth_user_change", args=(user.pk,))

        response = self.client.post(
            url,
            {
                "username": user.username,
                "first_name": "",
                "last_name": "",
                "email": "",
                "is_active": "on",
                "groups": [
                    str(group.pk)
                    for group in user.groups.filter(name__in=Role.values())
                ],
                "product_grants-0-id": str(existing.pk),
                "product_grants-0-product_ident": existing.product_ident,
                "product_grants-1-product_ident": "hrl2021",
                **self.inline_management_data(
                    product_total=2,
                    product_initial=1,
                ),
                "_save": "Save",
            },
        )

        self.assertEqual(response.status_code, 302)
        existing.refresh_from_db()
        added = user.product_grants.get(product_ident="hrl2021")
        self.assertEqual(existing.created_by_id, user.pk)
        self.assertEqual(added.created_by_id, self.actor.pk)

    @patch(
        "qc_tool.frontend.accounts.services.products."
        "available_product_descriptions",
        return_value={"clc2024": "CORINE Land Cover 2024"},
    )
    def test_duplicate_and_forged_products_are_rejected(self, _catalog):
        url = reverse("admin:auth_user_add")
        base_data = {
            "password1": "sufficient-password",
            "password2": "sufficient-password",
            **self.inline_management_data(
                product_total=2,
                product_initial=0,
            ),
            "_save": "Save",
        }

        duplicate = self.client.post(
            url,
            {
                **base_data,
                "username": "duplicate-products",
                "product_grants-0-product_ident": "clc2024",
                "product_grants-1-product_ident": "clc2024",
            },
        )
        forged = self.client.post(
            url,
            {
                **base_data,
                "username": "forged-product",
                "product_grants-0-product_ident": "not-configured",
            },
        )

        self.assertEqual(duplicate.status_code, 200)
        self.assertContains(duplicate, "already assigned")
        self.assertEqual(forged.status_code, 200)
        self.assertFalse(
            self.user_model.objects.filter(
                username__in=("duplicate-products", "forged-product"),
            ).exists()
        )

    @patch(
        "qc_tool.frontend.accounts.services.products."
        "available_product_descriptions",
    )
    def test_unavailable_catalog_keeps_legacy_grant_readonly(self, catalog):
        from qc_tool.frontend.accounts.services.products import (
            ProductCatalogUnavailable,
        )

        catalog.side_effect = ProductCatalogUnavailable("unavailable")
        user = self.user_model.objects.create_user(
            username="legacy-product-user",
            password="password",
        )
        UserProductGrant.objects.create(
            user=user,
            product_ident="legacy_product",
        )

        with self.assertLogs(
            "qc_tool.frontend.accounts.admin.products",
            level="WARNING",
        ):
            response = self.client.get(
                reverse("admin:auth_user_change", args=(user.pk,)),
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "unavailable legacy product")
        self.assertContains(response, "Product definitions are unavailable")

        with self.assertLogs(
            "qc_tool.frontend.accounts.admin.products",
            level="WARNING",
        ):
            rejected = self.client.post(
                reverse("admin:auth_user_add"),
                {
                    "username": "catalog-unavailable-user",
                    "password1": "sufficient-password",
                    "password2": "sufficient-password",
                    "product_grants-0-product_ident": "forged-product",
                    **self.inline_management_data(
                        product_total=1,
                        product_initial=0,
                    ),
                    "_save": "Save",
                },
            )

        self.assertEqual(rejected.status_code, 200)
        self.assertFalse(
            self.user_model.objects.filter(
                username="catalog-unavailable-user",
            ).exists()
        )

    def test_product_summary_and_exact_search_use_all_grants(self):
        first = self.user_model.objects.create_user(
            username="first-product-user",
            password="password",
        )
        second = self.user_model.objects.create_user(
            username="second-product-user",
            password="password",
        )
        UserProductGrant.objects.bulk_create(
            [
                UserProductGrant(user=first, product_ident="hrl2021"),
                UserProductGrant(user=first, product_ident="clc2024"),
                UserProductGrant(user=second, product_ident="other-product"),
            ]
        )
        request = RequestFactory().get("/admin/auth/user/")
        request.user = self.actor
        queryset = self.user_admin.get_queryset(request)
        searched, may_duplicate = self.user_admin.get_search_results(
            request,
            queryset,
            "clc2024",
        )

        self.assertEqual(list(searched), [first])
        self.assertTrue(may_duplicate)
        listed = queryset.get(pk=first.pk)
        self.assertEqual(
            self.user_admin.product_idents(listed),
            "clc2024, hrl2021",
        )
        response = self.client.get(
            reverse("admin:auth_user_changelist"),
            {"product_grants__product_ident": "clc2024"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context["cl"].result_list),
            [first],
        )
