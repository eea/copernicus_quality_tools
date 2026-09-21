"""Synthetic legacy identity conversion tests; no production data or writes."""

from copy import deepcopy
from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from qc_tool.database.legacy.accounts import prepare_accounts


def account_dump():
    return SimpleNamespace(tables={
        "auth_user": [{
            "id": "7", "password": "pbkdf2_sha256$600000$synthetic$hash",
            "last_login": "2026-07-01 09:00:00+02", "is_superuser": "f",
            "username": "MigratedUser", "first_name": "Example", "last_name": "User",
            "email": "example@example.test", "is_staff": "f", "is_active": "t",
            "date_joined": "2020-01-01 09:00:00+01",
        }],
        "dashboard_userprofile": [{"id": "2", "user_id": "7", "country": "Czechia", "product_family": "CLC2024"}],
        "auth_group": [{"id": "11", "name": "product_admin"}],
        "auth_user_groups": [{"id": "1", "user_id": "7", "group_id": "11"}],
        "django_content_type": [{"id": "3", "app_label": "auth", "model": "user"}],
        "auth_permission": [{"id": "8", "content_type_id": "3", "codename": "view_user"}],
        "auth_user_user_permissions": [{"id": "5", "user_id": "7", "permission_id": "8"}],
        "auth_group_permissions": [{"id": "9", "group_id": "11", "permission_id": "8"}],
    })


@override_settings(USE_TZ=False, TIME_ZONE="Europe/Prague")
class LegacyAccountsTests(SimpleTestCase):
    def test_retains_identity_hash_and_natural_permission_keys(self):
        dump = account_dump()
        prepared = prepare_accounts(dump)
        user = prepared.users[0]
        self.assertEqual(user.pk, 7)
        self.assertEqual(user.password, dump.tables["auth_user"][0]["password"])
        self.assertEqual(user.email, "example@example.test")
        self.assertEqual(user.username, "MigratedUser")
        self.assertEqual(user.date_joined.hour, 9)
        self.assertFalse(hasattr(prepared, "profiles"))
        self.assertEqual(prepared.permissions, {7: [("auth", "user", "view_user")]})
        self.assertNotIn(user.password, repr(prepared))

    def test_legacy_group_names_and_profile_do_not_grant_management_or_products(self):
        prepared = prepare_accounts(account_dump())
        self.assertEqual(prepared.role_names, {7: {"default"}})
        self.assertEqual(prepared.product_grants, [])
        self.assertEqual(prepared.omitted, {
            "legacy_profiles": 1, "legacy_profile_country_values": 1,
            "legacy_profile_product_family_values": 1, "obsolete_groups": 1,
            "obsolete_group_memberships": 1, "source_group_permissions": 1,
        })
        self.assertFalse(hasattr(prepared, "region_grants"))
        self.assertNotIn("Czechia", str(prepared.warnings))
        self.assertNotIn("product_admin", str(prepared.warnings))

    def test_superuser_and_inactive_state_are_preserved(self):
        dump = account_dump()
        dump.tables["auth_user"][0].update(is_superuser="t", is_active="f")
        prepared = prepare_accounts(dump, access_map={"users": {"7": {"roles": []}}})
        self.assertEqual(prepared.role_names[7], {"default", "admin"})
        self.assertTrue(prepared.users[0].is_superuser)
        self.assertTrue(prepared.users[0].is_staff)
        self.assertFalse(prepared.users[0].is_active)

    def test_staff_flag_alone_does_not_grant_admin_role(self):
        dump = account_dump()
        dump.tables["auth_user"][0]["is_staff"] = "t"
        prepared = prepare_accounts(dump)
        self.assertTrue(prepared.users[0].is_staff)
        self.assertEqual(prepared.role_names[7], {"default"})
        self.assertTrue(any("staff accounts" in warning for warning in prepared.warnings))

    def test_unsupported_password_hash_is_preserved_with_sanitized_warning(self):
        dump = account_dump()
        dump.tables["auth_user"][0]["password"] = "unsupported$synthetic$secret"
        prepared = prepare_accounts(dump)
        self.assertEqual(prepared.users[0].password, "unsupported$synthetic$secret")
        self.assertTrue(any("unsupported password hashes" in warning for warning in prepared.warnings))
        self.assertNotIn("synthetic", str(prepared.warnings))

    def test_explicit_access_map_assigns_exact_scopes_and_manager_staff_flag(self):
        prepared = prepare_accounts(account_dump(), access_map={"users": {"7": {
            "roles": ["product_manager"], "products": ["clc2024"],
        }}})
        self.assertEqual(prepared.role_names[7], {"default", "product_manager"})
        self.assertTrue(prepared.users[0].is_staff)
        self.assertEqual(prepared.product_grants[0].product_ident, "clc2024")
        self.assertEqual(prepared.product_grants[0].user_id, 7)

    def test_missing_profiles_do_not_create_replacement_records(self):
        dump = account_dump()
        second_user = dict(dump.tables["auth_user"][0], id="8", username="OtherUser")
        dump.tables["auth_user"].append(second_user)
        prepared = prepare_accounts(dump)
        self.assertEqual([user.pk for user in prepared.users], [7, 8])
        self.assertEqual(prepared.omitted["legacy_profiles"], 1)
        self.assertFalse(hasattr(prepared, "profiles"))

    def test_exact_canonical_legacy_roles_remain_roles(self):
        dump = account_dump()
        dump.tables["auth_group"][0]["name"] = "product_manager"
        prepared = prepare_accounts(dump)
        self.assertEqual(prepared.role_names[7], {"default", "product_manager"})
        self.assertEqual(prepared.omitted["obsolete_groups"], 0)
        self.assertEqual(prepared.omitted["obsolete_group_memberships"], 0)

    def test_rejects_ambiguous_case_variant_usernames(self):
        dump = account_dump()
        dump.tables["auth_user"].append(dict(dump.tables["auth_user"][0], id="8", username="MIGRATEDUSER"))
        with self.assertRaisesRegex(ValueError, "case-insensitively"):
            prepare_accounts(dump)

    def test_rejects_bad_foreign_keys_for_retained_account_relationships(self):
        for table, field in (
            ("auth_user_groups", "group_id"),
            ("auth_user_user_permissions", "permission_id"), ("auth_permission", "content_type_id"),
            ("auth_group_permissions", "group_id"),
        ):
            with self.subTest(table=table):
                dump = account_dump()
                dump.tables[table][0][field] = "999"
                with self.assertRaisesRegex(ValueError, "referenced row"):
                    prepare_accounts(dump)

    def test_obsolete_profile_relationships_do_not_block_core_data_conversion(self):
        dump = account_dump()
        dump.tables["dashboard_userprofile"][0]["user_id"] = "999"
        prepared = prepare_accounts(dump)
        self.assertEqual(len(prepared.users), 1)
        self.assertEqual(prepared.omitted["legacy_profiles"], 1)

    def test_removed_region_access_map_option_is_rejected_even_when_empty(self):
        for regions in ([], ["CZ"], "CZ"):
            with self.subTest(regions=regions), self.assertRaisesRegex(ValueError, "regions are no longer supported; assign products instead"):
                prepare_accounts(account_dump(), access_map={"users": {"7": {"regions": regions}}})

    def test_access_map_rejects_unknown_keys_users_roles_and_invalid_scopes(self):
        maps = [
            [], {"groups": {}}, {"users": []}, {"users": {"999": {}}},
            {"users": {"07": {}}}, {"users": {"7": {"is_superuser": True}}},
            {"users": {"7": {"roles": ["owner"]}}},
            {"users": {"7": {"products": ["CLC2024"]}}},
            {"users": {"7": {"products": ["../bad"]}}},
            {"users": {"7": {"products": ["clc2024", "clc2024"]}}},
            {"users": {"7": {"regions": [" "]}}},
            {"users": {"7": {"regions": "CZ"}}},
            {"users": {"7": {"roles": [True]}}},
        ]
        for access_map in maps:
            with self.subTest(access_map=access_map):
                with self.assertRaises(ValueError):
                    prepare_accounts(account_dump(), access_map=access_map)

    def test_does_not_mutate_source_rows(self):
        dump = account_dump()
        original = deepcopy(dump.tables)
        prepare_accounts(dump)
        self.assertEqual(dump.tables, original)
