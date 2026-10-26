"""Explicit bulk grants stay bounded, add-only and transactional."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from qc_tool.frontend.accounts.admin.role_permissions import synchronize_admin_role
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.accounts.services.product_grants import add_product_grants
from qc_tool.frontend.accounts.services.products import ProductCatalogUnavailable


class BulkProductGrantServiceTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.admin_group = synchronize_admin_role()
        self.actor = self.user_model.objects.create_user(username="bulk-service-admin")
        self.actor.groups.add(self.admin_group)
        self.target = self.user_model.objects.create_user(username="bulk-service-target")
        self.catalog = {
            "clms_euhydro_alpha": "River network",
            "clms_euhydro_beta": "Water bodies",
            "clms_hrlvlcc_alpha": "Land cover",
        }
        self.catalog_lookup = self.enterContext(patch(
            "qc_tool.frontend.accounts.services.products.available_product_descriptions",
            return_value=self.catalog,
        ))

    def assign(self, product_idents, *, user=None, actor=None):
        return add_product_grants(
            user=self.target if user is None else user,
            product_idents=product_idents,
            created_by=self.actor if actor is None else actor,
        )

    def add_permission(self):
        return Permission.objects.get(
            content_type__app_label=UserProductGrant._meta.app_label,
            codename="add_userproductgrant",
        )

    def test_830_definitions_use_one_catalog_snapshot_and_bounded_queries(self):
        catalog = {f"clms_euhydro_{index:04}": f"Definition {index}" for index in range(830)}
        self.catalog_lookup.return_value = catalog

        with CaptureQueriesContext(connection) as queries:
            created = self.assign(list(catalog))

        self.catalog_lookup.assert_called_once_with()
        # Includes authorization, target locking and database-sized INSERT
        # batches. A query per definition would exceed this by two orders.
        self.assertLessEqual(len(queries), 16)
        self.assertEqual(len(created), 830)
        self.assertTrue(all(grant.pk is not None for grant in created))
        self.assertEqual(
            set(self.target.product_grants.values_list("product_ident", flat=True)),
            set(catalog),
        )
        self.assertEqual(
            set(self.target.product_grants.values_list("created_by_id", flat=True)),
            {self.actor.pk},
        )

    def test_add_only_preserves_current_retired_and_creator_audit(self):
        previous_creator = self.user_model.objects.create_user(username="previous-grant-admin")
        current = UserProductGrant.objects.create(
            user=self.target, product_ident="clms_euhydro_alpha", created_by=previous_creator,
        )
        retired = UserProductGrant.objects.create(
            user=self.target, product_ident="retired_definition", created_by=previous_creator,
        )
        original = list(self.target.product_grants.values_list(
            "pk", "product_ident", "created_at", "created_by_id",
        ))

        created = self.assign([current.product_ident, "clms_euhydro_beta"])

        self.assertEqual([grant.product_ident for grant in created], ["clms_euhydro_beta"])
        self.assertEqual(created[0].created_by_id, self.actor.pk)
        self.assertEqual(
            list(self.target.product_grants.filter(pk__in=[current.pk, retired.pk]).values_list(
                "pk", "product_ident", "created_at", "created_by_id",
            )),
            original,
        )
        self.assertEqual(self.target.product_grants.count(), 3)

    def test_duplicates_and_repeated_submission_are_idempotent(self):
        selected = ["clms_euhydro_alpha", "clms_hrlvlcc_alpha", "clms_euhydro_alpha"]
        first = self.assign(selected)
        original = list(self.target.product_grants.values_list("pk", "created_at", "created_by_id"))

        repeated = self.assign(selected)

        self.assertEqual(len(first), 2)
        self.assertEqual(repeated, ())
        self.assertEqual(
            list(self.target.product_grants.values_list("pk", "created_at", "created_by_id")),
            original,
        )

    def test_empty_selection_does_not_need_catalog_or_change_existing_grants(self):
        existing = UserProductGrant.objects.create(user=self.target, product_ident="retired_definition")

        self.assertEqual(self.assign([]), ())

        self.catalog_lookup.assert_not_called()
        self.assertEqual(list(self.target.product_grants.values_list("pk", flat=True)), [existing.pk])

    def test_unknown_wildcard_and_parent_product_identifiers_reject_whole_selection(self):
        existing = UserProductGrant.objects.create(user=self.target, product_ident="retired_definition")
        # Parent-product scopes are valid in other grant workflows. This
        # specification picker must still accept only current definitions.
        with patch(
            "qc_tool.frontend.accounts.services.products.grantable_product_descriptions",
            return_value={**self.catalog, "clms_euhydro": "EUHydro product"},
        ):
            for invalid in ("unknown_definition", "clms_euhydro*", "clms_euhydro"):
                with self.subTest(product_ident=invalid):
                    with self.assertRaises(ValidationError):
                        self.assign(["clms_euhydro_alpha", invalid])

                    self.assertEqual(list(self.target.product_grants.values_list("pk", flat=True)), [existing.pk])

    def test_malformed_selection_rejects_before_writing(self):
        for selected in (None, "clms_euhydro_alpha", {"product": "clms_euhydro_alpha"}, [3], ["clms_euhydro_alpha", None]):
            with self.subTest(selection=selected):
                with self.assertRaises(ValidationError):
                    self.assign(selected)

                self.assertFalse(self.target.product_grants.exists())

        self.catalog_lookup.assert_not_called()

    def test_catalog_failure_leaves_existing_grants_unchanged(self):
        existing = UserProductGrant.objects.create(user=self.target, product_ident="retired_definition")
        self.catalog_lookup.side_effect = ProductCatalogUnavailable("catalog offline")

        with self.assertRaisesMessage(ValidationError, "catalog is unavailable"):
            self.assign(["clms_euhydro_alpha"])

        self.assertEqual(list(self.target.product_grants.values_list("pk", flat=True)), [existing.pk])

    def test_invalid_catalog_identifier_still_runs_model_field_validation(self):
        too_long = "x" * 65
        self.catalog_lookup.return_value = {**self.catalog, too_long: "Invalid catalog key"}

        with self.assertRaises(ValidationError):
            self.assign(["clms_euhydro_alpha", too_long])

        self.assertFalse(self.target.product_grants.exists())

    def test_generic_add_permission_does_not_replace_qc_administrator_role(self):
        actor = self.user_model.objects.create_user(username="grant-permission-only")
        actor.user_permissions.add(self.add_permission())

        with self.assertRaises(PermissionDenied):
            self.assign(["clms_euhydro_alpha"], actor=actor)

        self.catalog_lookup.assert_not_called()
        self.assertFalse(self.target.product_grants.exists())

    def test_qc_administrator_still_needs_add_grant_permission(self):
        self.admin_group.permissions.remove(self.add_permission())
        actor = self.user_model.objects.get(pk=self.actor.pk)

        with self.assertRaises(PermissionDenied):
            self.assign(["clms_euhydro_alpha"], actor=actor)

        self.catalog_lookup.assert_not_called()
        self.assertFalse(self.target.product_grants.exists())

    def test_inactive_administrator_cannot_assign_grants(self):
        self.actor.is_active = False

        with self.assertRaises(PermissionDenied):
            self.assign(["clms_euhydro_alpha"])

        self.catalog_lookup.assert_not_called()
        self.assertFalse(self.target.product_grants.exists())

    def test_role_administrator_cannot_modify_superuser_scope(self):
        target = self.user_model.objects.create_superuser(username="protected-grant-root")

        with self.assertRaises(PermissionDenied):
            self.assign(["clms_euhydro_alpha"], user=target)

        self.catalog_lookup.assert_not_called()
        self.assertFalse(target.product_grants.exists())

    def test_superuser_can_assign_scope_to_another_superuser(self):
        actor = self.user_model.objects.create_superuser(username="grant-root-actor")
        target = self.user_model.objects.create_superuser(username="grant-root-target")

        created = self.assign(["clms_euhydro_alpha"], user=target, actor=actor)

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].user_id, target.pk)
        self.assertEqual(created[0].created_by_id, actor.pk)

    def test_unsaved_target_is_rejected_without_writes(self):
        with self.assertRaisesMessage(ValidationError, "Save the user"):
            self.assign(["clms_euhydro_alpha"], user=self.user_model(username="not-saved"))

        self.catalog_lookup.assert_not_called()
        self.assertFalse(UserProductGrant.objects.exists())

    def test_later_insert_batch_failure_rolls_back_earlier_successful_batch(self):
        existing = UserProductGrant.objects.create(user=self.target, product_ident="retired_definition")
        catalog = {f"clms_euhydro_{index:04}": f"Definition {index}" for index in range(830)}
        self.catalog_lookup.return_value = catalog
        attempts = 0
        successful_batches = 0
        original_batch_size = connection.ops.bulk_batch_size

        def small_batches(fields, objects):
            return min(50, original_batch_size(fields, objects))

        def fail_second_insert(execute, sql, params, many, context):
            nonlocal attempts, successful_batches
            grant_insert = sql.lstrip().startswith(
                f"INSERT INTO {connection.ops.quote_name(UserProductGrant._meta.db_table)} "
            )
            if grant_insert:
                attempts += 1
                if attempts == 2:
                    raise IntegrityError("simulated later grant batch failure")
            result = execute(sql, params, many, context)
            if grant_insert:
                successful_batches += 1
            return result

        with patch.object(connection.ops, "bulk_batch_size", side_effect=small_batches):
            with connection.execute_wrapper(fail_second_insert):
                with self.assertRaises(IntegrityError):
                    self.assign(list(catalog))

        self.assertEqual(attempts, 2)
        self.assertEqual(successful_batches, 1)
        self.assertEqual(list(self.target.product_grants.values_list("pk", flat=True)), [existing.pk])
