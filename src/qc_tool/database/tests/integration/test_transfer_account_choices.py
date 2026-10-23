"""Selected user imports preserve identity, access and receipt recovery."""

from copy import deepcopy
from datetime import timedelta
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.sessions.models import Session
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.models.signals import post_save
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from qc_tool.database.models import TransferReceipt
from qc_tool.database.transfers import service, store
from qc_tool.database.transfers.account_import import PROFILE_FIELDS
from qc_tool.database.transfers.contracts import TransferError
from qc_tool.database.transfers.records import apply_records, export_records, plan_records, verify_records
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import PersonalAccessToken, UserProductGrant
from qc_tool.frontend.dashboard.models import Delivery, Job
from qc_tool.frontend.dashboard.services import maintenance
from qc_tool.frontend.dashboard.services.maintenance.operations import active_operation


class AccountChoiceRecordTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.actor = User.objects.create_superuser("account-operator", "operator@example.test", "operator-password")
        self.target = User.objects.create_superuser("existing-user", "old@example.test", "retained-password",
                                                   first_name="Original", last_name="Person")
        self.source = User.objects.create_user("source-existing", "incoming@example.test", first_name="Incoming", last_name="Name")
        self.new_source = User.objects.create_user("source-new", "new@example.test")
        self.skipped_source = User.objects.create_user("source-skipped", "skip@example.test")
        self.payload = export_records("accounts", [self.source.pk, self.new_source.pk, self.skipped_source.pk])
        self.keys = {"existing": str(self.source.pk), "new": str(self.new_source.pk), "skip": str(self.skipped_source.pk)}
        for row in self.payload["accounts"]:
            row["username"] = {self.keys["existing"]: self.target.username,
                               self.keys["new"]: "incoming-new", self.keys["skip"]: "incoming-skipped"}[row["key"]]
        self.payload["accounts"][1]["roles"] = [Role.ADMIN.value]
        self.payload["accounts"][1]["grants"] = ["untrusted-source-grant"]

    def choices(self, **overrides):
        choices = {self.keys["existing"]: {"action": "replace", "target_id": self.target.pk},
                   self.keys["new"]: {"action": "import", "target_id": None},
                   self.keys["skip"]: {"action": "skip", "target_id": None}}
        for name, choice in overrides.items():
            choices[self.keys[name]] = choice
        return choices

    def profile_only(self):
        return self.choices(new={"action": "skip"})

    def test_collision_needs_a_decision_and_shows_only_allowlisted_evidence(self):
        plan = plan_records(self.payload)
        row = plan["accounts"][0]
        self.assertTrue(plan["blockers"])
        self.assertEqual(row["disposition"], "")
        self.assertEqual({choice["value"] for choice in row["choices"]}, {"reuse", "replace", "skip"})
        self.assertEqual(row["candidate_targets"][0]["id"], self.target.pk)
        self.assertEqual({difference["field"] for difference in row["differences"]}, {"First name", "Last name", "Email"})
        self.assertNotIn(self.target.password, str(plan))
        self.assertNotIn("is_superuser", str(row["candidate_targets"]))
        self.assertEqual(plan["accounts"][1]["differences"][0]["current"], None)

    def test_selection_adds_only_chosen_users_without_importing_authority(self):
        before = get_user_model().objects.count()
        choices = self.choices(existing={"action": "skip"})
        plan = plan_records(self.payload, account_choices=choices)
        self.assertEqual(plan["account_summary"], {"total": 3, "selected": 1, "create": 1,
                         "reuse": 0, "replace": 0, "skip": 2, "blocked": 0})
        result = apply_records(self.payload, plan)
        imported = get_user_model().objects.get(username="incoming-new")
        self.assertEqual(get_user_model().objects.count(), before + 1)
        self.assertFalse(imported.is_active or imported.is_staff or imported.is_superuser or imported.has_usable_password())
        self.assertEqual(set(imported.groups.values_list("name", flat=True)), {Role.DEFAULT.value})
        self.assertFalse(imported.user_permissions.exists() or imported.product_grants.exists())
        self.assertFalse(get_user_model().objects.filter(username="incoming-skipped").exists())
        self.assertEqual(result["skipped_account_keys"], [self.keys["existing"], self.keys["skip"]])
        self.assertEqual(set(result["user_mappings"]), {self.keys["new"]})
        self.assertTrue(verify_records(self.payload, result))

    def test_replace_changes_only_profile_fields_and_keeps_connected_security(self):
        permission = Permission.objects.order_by("pk").first()
        self.target.user_permissions.add(permission)
        grant = UserProductGrant.objects.create(user=self.target, product_ident="retained-product", created_by=self.actor)
        token = PersonalAccessToken.objects.create(user=self.target, name="Retained API", secret_digest="sha256$" + "a" * 64,
                                                   token_hint="qct_retained", permission_snapshot=["upload_delivery"])
        Session.objects.create(session_key="retained-account-session", session_data="retained-data",
                               expire_date=timezone.now() + timedelta(days=1))
        delivery = Delivery.objects.create(user=self.target, filename="retained.zip", size_bytes=1)
        job = Job.objects.create(delivery=delivery, requested_by=self.target, job_status="ok")
        before_user = get_user_model().objects.values().get(pk=self.target.pk)
        before_token = PersonalAccessToken.objects.values().get(pk=token.pk)
        before_grant = UserProductGrant.objects.values().get(pk=grant.pk)
        before_session = list(Session.objects.values())
        before_groups = list(self.target.groups.values_list("pk", flat=True))
        before_permissions = list(self.target.user_permissions.values_list("pk", flat=True))
        result = apply_records(self.payload, plan_records(self.payload, account_choices=self.profile_only()))
        after_user = get_user_model().objects.values().get(pk=self.target.pk)
        self.assertEqual({key: value for key, value in after_user.items() if key not in PROFILE_FIELDS},
                         {key: value for key, value in before_user.items() if key not in PROFILE_FIELDS})
        self.assertEqual([after_user[field] for field in PROFILE_FIELDS], ["Incoming", "Name", "incoming@example.test"])
        self.assertEqual(PersonalAccessToken.objects.values().get(pk=token.pk), before_token)
        self.assertEqual(UserProductGrant.objects.values().get(pk=grant.pk), before_grant)
        self.assertEqual(list(Session.objects.values()), before_session)
        self.assertEqual(list(self.target.groups.values_list("pk", flat=True)), before_groups)
        self.assertEqual(list(self.target.user_permissions.values_list("pk", flat=True)), before_permissions)
        delivery.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual(delivery.user_id, self.target.pk)
        self.assertEqual(job.requested_by_id, self.target.pk)
        self.assertEqual(result["updated_counts"], {"accounts": 1})
        self.assertEqual(result["created_counts"], {})
        self.assertTrue(verify_records(self.payload, result))

    def test_reuse_does_not_replace_even_different_profile_values(self):
        before = get_user_model().objects.values().get(pk=self.target.pk)
        choices = self.profile_only()
        choices[self.keys["existing"]] = {"action": "reuse", "target_id": self.target.pk}
        result = apply_records(self.payload, plan_records(self.payload, account_choices=choices))
        self.assertEqual(get_user_model().objects.values().get(pk=self.target.pk), before)
        self.assertEqual(result["reused_counts"], {"accounts": 1})
        self.assertEqual(result["updated_counts"], {})
        self.assertTrue(verify_records(self.payload, result))

    def test_replace_cannot_rename_or_target_an_unrelated_identity(self):
        choices = self.profile_only()
        choices[self.keys["existing"]] = {"action": "replace", "target_id": self.actor.pk}
        plan = plan_records(self.payload, account_choices=choices)
        self.assertIn("matching username", " ".join(plan["blockers"]))
        with self.assertRaisesMessage(TransferError, "blockers"):
            apply_records(self.payload, plan)

    def test_malformed_or_forged_choices_never_change_users(self):
        before = list(get_user_model().objects.order_by("pk").values())
        for choices in (
            {"unknown-source": {"action": "skip"}},
            {self.keys["existing"]: {"action": "delete"}},
            {self.keys["existing"]: {"action": []}},
            {self.keys["existing"]: {"action": "replace", "target_id": True}},
            {self.keys["existing"]: {"action": "replace"}},
            {self.keys["new"]: {"action": "import", "target_id": self.target.pk}},
            {self.keys["existing"]: {"action": "replace", "target_id": self.target.pk, "password": "forged"}},
        ):
            with self.subTest(choices=choices), self.assertRaises(TransferError):
                plan_records(self.payload, account_choices=choices)
        self.assertEqual(list(get_user_model().objects.order_by("pk").values()), before)

    def test_one_target_cannot_be_selected_for_multiple_incoming_users(self):
        choices = self.choices(new={"action": "reuse", "target_id": self.target.pk})
        with self.assertRaisesMessage(TransferError, "distinct destination"):
            plan_records(self.payload, account_choices=choices)

    def test_skipping_every_user_requires_a_new_selection(self):
        choices = {row["key"]: {"action": "skip"} for row in self.payload["accounts"]}
        plan = plan_records(self.payload, account_choices=choices)
        self.assertIn("Select at least one", " ".join(plan["blockers"]))
        with self.assertRaises(TransferError):
            apply_records(self.payload, plan)

    def test_application_graph_cannot_use_profile_replacement(self):
        application = export_records("application")
        for choices in ({}, {self.keys["existing"]: {"action": "replace", "target_id": self.target.pk}}):
            with self.subTest(choices=choices), self.assertRaisesMessage(TransferError, "only to user-account"):
                plan_records(application, account_choices=choices)

    def test_changed_identity_profile_or_authority_invalidates_the_review(self):
        mutations = (
            lambda: get_user_model().objects.filter(pk=self.target.pk).update(first_name="Changed outside import"),
            lambda: get_user_model().objects.filter(pk=self.target.pk).update(password="outside-password-change"),
            lambda: get_user_model().objects.filter(pk=self.target.pk).update(is_active=False),
            lambda: self.target.groups.add(Group.objects.create(name="additional-reviewed-role")),
            lambda: UserProductGrant.objects.create(user=self.target, product_ident="changed-grant"),
            lambda: Session.objects.create(session_key="new-session-after-plan", session_data="outside",
                                            expire_date=timezone.now() + timedelta(days=1)),
        )
        for mutate in mutations:
            with transaction.atomic():
                plan = plan_records(self.payload, account_choices=self.profile_only())
                mutate()
                with self.assertRaisesMessage(TransferError, "stale"):
                    apply_records(self.payload, plan)
                transaction.set_rollback(True)

    def test_receipt_verification_detects_security_changes_after_commit(self):
        result = apply_records(self.payload, plan_records(self.payload, account_choices=self.profile_only()))
        UserProductGrant.objects.create(user=self.target, product_ident="unexpected-grant")
        with self.assertRaisesMessage(TransferError, "after commit"):
            verify_records(self.payload, result)

    def test_failure_rolls_back_profile_updates_and_new_users_together(self):
        before = list(get_user_model().objects.order_by("pk").values())
        plan = plan_records(self.payload, account_choices=self.choices())
        with self.assertRaisesMessage(RuntimeError, "before receipt"):
            with transaction.atomic():
                apply_records(self.payload, plan)
                raise RuntimeError("Failure before receipt commit")
        self.assertEqual(list(get_user_model().objects.order_by("pk").values()), before)

    def test_unexpected_new_user_authority_rolls_back_before_commit(self):
        User = get_user_model()
        before = list(User.objects.order_by("pk").values())
        plan = plan_records(self.payload, account_choices=self.choices())

        def unexpected_access(sender, instance, created, **kwargs):
            if created and instance.username == "incoming-new":
                sender.objects.filter(pk=instance.pk).update(is_staff=True)

        post_save.connect(unexpected_access, sender=User, weak=False)
        try:
            with self.assertRaisesMessage(TransferError, "inactive access boundary"):
                with transaction.atomic():
                    apply_records(self.payload, plan)
        finally:
            post_save.disconnect(unexpected_access, sender=User)
        self.assertEqual(list(User.objects.order_by("pk").values()), before)

    def test_validated_profile_bytes_are_retained_without_normalizing_email(self):
        self.payload["accounts"][1]["email"] = "New@EXAMPLE.TEST"
        plan = plan_records(self.payload, account_choices=self.choices(existing={"action": "skip"}))
        result = apply_records(self.payload, plan)
        self.assertEqual(get_user_model().objects.get(username="incoming-new").email, "New@EXAMPLE.TEST")
        self.assertTrue(verify_records(self.payload, result))


class AccountChoiceServiceTests(TransactionTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="qc-account-choice-tests-")
        self.addCleanup(temporary.cleanup)
        override = override_settings(QC_TOOL_MAINTENANCE_DIR=temporary.name + "/maintenance",
                                     QC_TOOL_TRANSFER_DIR=temporary.name + "/transfers", MAINTENANCE_MODE=False)
        override.enable()
        self.addCleanup(override.disable)
        User = get_user_model()
        self.actor = User.objects.create_superuser("operator", "operator@example.test", "test-password")
        self.target = User.objects.create_user("replace-me", "incoming@example.test", "retained-password", first_name="Incoming")
        self.new = User.objects.create_user("import-me", "new@example.test")
        self.skipped = User.objects.create_user("skip-me", "skip@example.test")
        self.keys = {"replace": str(self.target.pk), "new": str(self.new.pk), "skip": str(self.skipped.pk)}
        launch = patch.object(service, "_launch")
        launch.start()
        self.addCleanup(launch.stop)
        self.generation = maintenance.enable(self.actor, 0)["generation"]
        maintenance.advance(self.generation)
        selection = {"profile": "accounts", "user_ids": [self.target.pk, self.new.pk, self.skipped.pk]}
        preview = service.export_preview(selection, self.actor)
        exported = service.create_export(selection, self.actor, preview["review_hash"], self.generation)
        service.run_operation(exported["id"])
        stream, _metadata = service.download_operation(exported["id"], self.actor)
        with stream:
            self.package = stream.read()
        # Simulate target identities after an earlier account export, only in
        # this disposable fixture. No existing source identity is deleted.
        User.objects.filter(pk=self.target.pk).update(first_name="Original", email="old@example.test")
        User.objects.filter(pk=self.new.pk).update(username="retained-source-copy")
        self.operation = service.stage_import(SimpleUploadedFile("users.zip", self.package), self.actor)
        self.choices = {self.keys["replace"]: {"action": "replace", "target_id": self.target.pk},
                        self.keys["new"]: {"action": "import", "target_id": None},
                        self.keys["skip"]: {"action": "skip", "target_id": None}}

    def planned(self):
        return service.plan_import(self.operation["id"], self.actor, account_choices=self.choices)

    def queued(self):
        plan = self.planned()
        return service.start_import(self.operation["id"], self.actor, plan["plan_hash"], self.generation, True)

    def test_service_exposes_reviewed_choices_and_recovery_hides_private_auth_evidence(self):
        plan = self.planned()
        self.assertEqual(plan["account_summary"]["replace"], 1)
        self.assertEqual(plan["account_summary"]["skip"], 1)
        self.assertEqual(plan["account_choices"], self.choices)
        self.assertEqual(plan["account_mappings"][0]["first_name"], "Incoming")
        self.assertEqual(plan["account_mappings"][0]["differences"][0]["current"], "Original")
        operation = service.start_import(self.operation["id"], self.actor, plan["plan_hash"], self.generation, True)
        result = service.run_operation(operation["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["updated_counts"], {"accounts": 1})
        self.assertEqual(result["result"]["created_counts"], {"accounts": 1})
        self.assertNotIn("target_digest", result["result"])
        self.assertNotIn("package_digest", result["result"])
        receipt = TransferReceipt.objects.get(operation_id=operation["id"])
        self.assertIn("target_digest", receipt.summary)
        self.assertEqual(receipt.summary["account_choices"], self.choices)
        self.target.refresh_from_db()
        self.assertEqual(self.target.first_name, "Incoming")
        self.assertTrue(self.target.check_password("retained-password"))
        self.assertFalse(get_user_model().objects.get(username="import-me").is_active)
        self.assertIsNone(active_operation())
        repeated = service.stage_import(SimpleUploadedFile("same-users.zip", self.package), self.actor)
        plan = service.plan_import(repeated["id"], self.actor, account_choices=self.choices)
        self.assertFalse(plan["can_apply"])
        self.assertIn("already been imported", " ".join(plan["blockers"]))

    def test_partial_choice_updates_preserve_saved_selections_and_change_the_hash(self):
        before = self.planned()
        after = service.plan_import(self.operation["id"], self.actor,
                                    account_choices={self.keys["new"]: {"action": "skip"}})
        self.assertEqual(after["account_choices"][self.keys["replace"]], self.choices[self.keys["replace"]])
        self.assertEqual(after["account_choices"][self.keys["skip"]], self.choices[self.keys["skip"]])
        self.assertEqual(after["account_choices"][self.keys["new"]], {"action": "skip", "target_id": None})
        self.assertNotEqual(after["plan_hash"], before["plan_hash"])
        with self.assertRaisesMessage(TransferError, "Review and confirm"):
            service.start_import(self.operation["id"], self.actor, before["plan_hash"], self.generation, True)

    def test_target_security_change_prevents_admission_before_pin(self):
        plan = self.planned()
        get_user_model().objects.filter(pk=self.target.pk).update(is_staff=True)
        with self.assertRaisesMessage(TransferError, "destination or package changed"):
            service.start_import(self.operation["id"], self.actor, plan["plan_hash"], self.generation, True)
        self.assertIsNone(active_operation())
        self.assertFalse(TransferReceipt.objects.exists())

    def test_stale_admin_choices_cannot_overwrite_a_newer_review(self):
        original = self.planned()
        current = service.plan_import(
            self.operation["id"], self.actor,
            account_choices={self.keys["new"]: {"action": "skip"}},
            expected_plan_hash=original["plan_hash"],
        )
        saved = deepcopy(store.read_operation(self.operation["id"]))
        with self.assertRaisesMessage(TransferError, "review changed"):
            service.plan_import(
                self.operation["id"], self.actor,
                account_choices={self.keys["new"]: {"action": "import"}},
                expected_plan_hash=original["plan_hash"],
            )
        self.assertEqual(store.read_operation(self.operation["id"]), saved)
        self.assertEqual(saved["plan"]["plan_hash"], current["plan_hash"])
        self.assertEqual(saved["core_plan"]["account_choices"][self.keys["new"]]["action"], "skip")
        self.assertIsNone(active_operation())

    def test_receipt_failure_rolls_back_replacement_before_retry(self):
        operation = self.queued()
        with patch.object(TransferReceipt.objects, "create", side_effect=RuntimeError("Injected receipt failure")):
            with self.assertRaises(TransferError):
                service.run_operation(operation["id"])
        self.target.refresh_from_db()
        self.assertEqual(self.target.first_name, "Original")
        self.assertFalse(get_user_model().objects.filter(username="import-me").exists())
        service.recover_operation(operation["id"], self.actor, "retry")
        self.assertEqual(service.run_operation(operation["id"])["status"], "completed")
        self.assertEqual(TransferReceipt.objects.count(), 1)

    def test_lost_commit_ack_recovers_without_reapplying_profile_updates(self):
        operation = self.queued()
        save = store.save_operation
        def lose_ack(value):
            if value["status"] == "completed":
                raise OSError("Injected lost commit acknowledgement")
            return save(value)
        with patch.object(store, "save_operation", side_effect=lose_ack):
            with self.assertRaises(TransferError):
                service.run_operation(operation["id"])
        receipt = TransferReceipt.objects.get(operation_id=operation["id"])
        imported = get_user_model().objects.get(username="import-me")
        service.recover_operation(operation["id"], self.actor, "retry")
        with patch.object(service, "apply_records", side_effect=AssertionError("Committed user updates must not run twice")):
            self.assertEqual(service.run_operation(operation["id"])["status"], "completed")
        self.assertEqual(get_user_model().objects.get(username="import-me").pk, imported.pk)
        self.assertEqual(TransferReceipt.objects.get().pk, receipt.pk)
