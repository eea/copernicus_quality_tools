"""Additive receipts protect existing access on disposable model-created DBs."""

from copy import deepcopy
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.test import TestCase

from qc_tool.database.models import TransferReceipt
from qc_tool.database.transfers.errors import TransferError
from qc_tool.database.transfers.records import apply_records, export_records, plan_records, verify_records
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import UserProductGrant


class AdditiveAccessEvidenceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.actor = User.objects.create_superuser("access-operator", "admin@example.test", "password")
        self.owner = User.objects.create_user("existing-owner", "owner@example.test", "password")
        content_type = ContentType.objects.get_for_model(User)
        self.permission = Permission.objects.create(content_type=content_type,
            codename="existing_transfer_access", name="Existing transfer access")
        self.other_permission = Permission.objects.create(content_type=content_type,
            codename="extra_transfer_access", name="Extra transfer access")
        User.user_permissions.through.objects.create(user_id=self.owner.pk, permission_id=self.permission.pk)
        self.access_group = Group.objects.create(name="existing-access-group")
        User.groups.through.objects.create(user_id=self.owner.pk, group_id=self.access_group.pk)
        Group.permissions.through.objects.create(group_id=self.access_group.pk, permission_id=self.permission.pk)
        self.grant = UserProductGrant.objects.create(user=self.owner, product_ident="existing-product", created_by=self.actor)
        self.payload = export_records("application")
        incoming = deepcopy(next(row for row in self.payload["accounts"] if row["key"] == str(self.owner.pk)))
        incoming.update(key="999999", username="new-inactive-owner")
        self.payload["accounts"].append(incoming)
        self.payload["selection"]["user_ids"].append(999999)
        mappings = {str(user.pk): user.pk for user in (self.actor, self.owner)}
        self.result = apply_records(self.payload, plan_records(self.payload, mappings), actor=self.actor)

    def test_default_role_for_new_account_does_not_change_existing_access_evidence(self):
        verified = verify_records(self.payload, self.result)
        self.assertEqual(verified["verified_counts"], {"accounts": 1})
        imported = get_user_model().objects.get(username="new-inactive-owner")
        self.assertEqual(set(imported.groups.values_list("name", flat=True)), {Role.DEFAULT.value})
        self.assertFalse(imported.product_grants.exists())
        self.assertFalse(imported.user_permissions.exists())

    def assert_access_mutation_detected(self, mutate):
        before = get_user_model().objects.values().get(pk=self.owner.pk)
        mutate()
        # These mutations deliberately avoid auth signals or User.save(), so
        # access evidence must catch them independently of the user-row hash.
        self.assertEqual(get_user_model().objects.values().get(pk=self.owner.pk), before)
        with self.assertRaisesMessage(TransferError, "Pre-existing account access changed"):
            verify_records(self.payload, self.result)

    def test_added_membership_to_existing_user_is_detected(self):
        manager = Group.objects.get(name=Role.PRODUCT_MANAGER.value)
        self.assert_access_mutation_detected(lambda: get_user_model().groups.through.objects.create(
            user_id=self.owner.pk, group_id=manager.pk))

    def test_removed_membership_from_existing_user_is_detected(self):
        self.assert_access_mutation_detected(lambda: get_user_model().groups.through.objects.filter(
            user_id=self.owner.pk).delete())

    def test_added_direct_permission_to_existing_user_is_detected(self):
        self.assert_access_mutation_detected(lambda: get_user_model().user_permissions.through.objects.create(
            user_id=self.owner.pk, permission_id=self.other_permission.pk))

    def test_removed_direct_permission_from_existing_user_is_detected(self):
        self.assert_access_mutation_detected(lambda: get_user_model().user_permissions.through.objects.filter(
            user_id=self.owner.pk, permission_id=self.permission.pk).delete())

    def test_added_changed_and_removed_existing_product_grants_are_detected(self):
        mutations = (
            lambda: UserProductGrant.objects.create(user=self.owner, product_ident="extra-product"),
            lambda: UserProductGrant.objects.filter(pk=self.grant.pk).update(product_ident="changed-product"),
            lambda: UserProductGrant.objects.filter(pk=self.grant.pk).delete(),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                savepoint = transaction.savepoint()
                try:
                    self.assert_access_mutation_detected(mutate)
                finally:
                    transaction.savepoint_rollback(savepoint)

    def test_receipt_without_access_baseline_cannot_finish_verification(self):
        incomplete = deepcopy(self.result)
        incomplete["baseline"].pop("access")
        with self.assertRaisesMessage(TransferError, "missing existing account access evidence"):
            verify_records(self.payload, incomplete)

    def test_oversized_target_fails_before_an_unbounded_snapshot_is_built(self):
        mappings = self.result["user_mappings"]
        with patch("qc_tool.database.transfers.merge.MAX_TARGET_SNAPSHOT_ROWS", 1):
            with self.assertRaisesMessage(TransferError, "row additive verification limit"):
                plan_records(self.payload, mappings)

    def test_added_permissions_to_an_existing_group_are_detected(self):
        Group.permissions.through.objects.create(group_id=self.access_group.pk, permission_id=self.other_permission.pk)
        with self.assertRaisesMessage(TransferError, "Pre-existing group permissions changed"):
            verify_records(self.payload, self.result)

    def test_removed_permissions_from_an_existing_group_are_detected(self):
        Group.permissions.through.objects.filter(group_id=self.access_group.pk, permission_id=self.permission.pk).delete()
        with self.assertRaisesMessage(TransferError, "Pre-existing group permissions changed"):
            verify_records(self.payload, self.result)

    def test_existing_group_name_change_is_detected_without_a_user_row_change(self):
        before = get_user_model().objects.values().get(pk=self.owner.pk)
        Group.objects.filter(pk=self.access_group.pk).update(name="changed-access-group")
        self.assertEqual(get_user_model().objects.values().get(pk=self.owner.pk), before)
        with self.assertRaisesMessage(TransferError, "Pre-existing authorization definitions changed"):
            verify_records(self.payload, self.result)

    def test_existing_permission_identity_change_is_detected(self):
        Permission.objects.filter(pk=self.permission.pk).update(codename="changed_permission_identity")
        with self.assertRaisesMessage(TransferError, "Pre-existing authorization definitions changed"):
            verify_records(self.payload, self.result)

    def test_existing_permission_content_type_change_is_detected(self):
        ContentType.objects.filter(pk=self.permission.content_type_id).update(app_label="changed-application")
        with self.assertRaisesMessage(TransferError, "Pre-existing authorization definitions changed"):
            verify_records(self.payload, self.result)

    def test_prior_source_account_identity_cannot_be_rebound_to_a_recreated_username(self):
        TransferReceipt.objects.create(package_id=uuid4(), package_sha256="a" * 64, operation_id=uuid4(),
            plan_sha256="b" * 64, profile="application", actor=self.actor, actor_name=self.actor.username,
            summary=self.result)
        User = get_user_model()
        User.objects.filter(pk=self.owner.pk).update(username="renamed-original-owner")
        replacement = User.objects.create_user("existing-owner", "replacement@example.test", "password")
        mappings = dict(self.result["user_mappings"])
        mappings[str(self.owner.pk)] = replacement.pk
        plan = plan_records(self.payload, mappings)
        self.assertTrue(any("cannot be rebound" in blocker for blocker in plan["blockers"]))
        self.assertEqual(TransferReceipt.objects.count(), 1)
