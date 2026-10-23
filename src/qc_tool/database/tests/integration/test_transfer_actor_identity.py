"""Transfer identities remain bound to their database across reviewed cutovers."""

from copy import copy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase, override_settings

from qc_tool.database.models import TransferReceipt
from qc_tool.database.transfers import service, store
from qc_tool.frontend.dashboard.services import maintenance


@override_settings(PASSWORD_HASHERS=("django.contrib.auth.hashers.MD5PasswordHasher",))
class TransferActorIdentityTests(TransactionTestCase):
    def setUp(self):
        root = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(override_settings(
            QC_TOOL_MAINTENANCE_DIR=root / "maintenance", QC_TOOL_TRANSFER_DIR=root / "transfers",
            MAINTENANCE_MODE=False, QC_TOOL_TRANSFER_MIN_FREE_BYTES=1024**2,
        ))
        self.actor = get_user_model().objects.create_superuser("identity-operator", "", "original-password")
        self.enterContext(patch.object(service, "_launch"))
        self.generation = maintenance.enable(self.actor, 0)["generation"]
        self.assertEqual(maintenance.advance(self.generation)["phase"], "ready")

    def origin_actor(self):
        # An authenticated administrator from the retained source can have a
        # different numeric ID from the matching account on the active copy.
        actor = copy(self.actor)
        actor._state = copy(self.actor._state)
        actor.pk = self.actor.pk + 100000
        return actor

    def queued_import(self):
        source = get_user_model().objects.create_user("identity-imported-user", "", "source-password")
        selection = {"profile": "accounts", "user_ids": [source.pk]}
        review = service.export_preview(selection, self.actor)
        exported = service.create_export(selection, self.actor, review["review_hash"], self.generation)
        self.assertEqual(service.run_operation(exported["id"])["status"], "completed")
        stream, _metadata = service.download_operation(exported["id"], self.actor)
        with stream:
            data = stream.read()
        source.delete()
        operation = service.stage_import(SimpleUploadedFile("identity.zip", data), self.actor)
        plan = service.plan_import(operation["id"], self.actor)
        return service.start_import(operation["id"], self.actor, plan["plan_hash"], self.generation, True)

    def test_actor_identity_records_current_database_for_default_connection(self):
        with patch.object(service.database_selection, "current_database", return_value="active-copy"):
            self.assertEqual(service._actor_identity(self.actor), {
                "actor_id": self.actor.pk, "actor_name": self.actor.username, "actor_database": "active-copy",
            })

    def test_actor_identity_preserves_pinned_origin_instead_of_active_database(self):
        actor = copy(self.actor)
        actor._state = copy(self.actor._state)
        actor._state.db = "retained_origin"
        with patch.object(service, "connections", {"retained_origin": SimpleNamespace(settings_dict={"NAME": "source-copy"})}), \
                patch.object(service.database_selection, "current_database", return_value="active-copy"):
            self.assertEqual(service._actor_identity(actor)["actor_database"], "source-copy")

    def test_runner_rejects_same_numeric_id_with_different_username(self):
        operation = {"actor_id": self.actor.pk, "actor_name": "different-administrator"}
        with self.assertRaisesMessage(service.TransferError, "administrator identity changed"):
            service._runner_actor(operation)

    def test_legacy_journal_without_origin_resolves_current_identity(self):
        operation = {"actor_id": self.actor.pk, "actor_name": self.actor.username}
        resolved = service._runner_actor(operation)
        self.assertEqual(resolved.pk, self.actor.pk)
        self.assertEqual(resolved.username, self.actor.username)

    def test_native_runner_resolves_origin_on_pinned_alias_during_same_maintenance_window(self):
        operation = {"kind": "export", "profile": "database", "actor_id": self.actor.pk,
                     "actor_name": self.actor.username, "actor_database": "source-copy"}
        origin_connection = MagicMock()
        query = MagicMock()
        query.get.return_value = self.actor
        with patch.object(service.database_selection, "current_database", return_value="active-copy"), \
                patch.object(service.database_selection, "read_state", return_value={"maintenance_generation": self.generation}), \
                patch.object(service.database_selection, "alias_for_database", return_value="pinned_source") as alias, \
                patch.object(get_user_model().objects, "using", return_value=query) as using, \
                patch.object(service, "connections", {"pinned_source": origin_connection}):
            self.assertEqual(service._runner_actor(operation), self.actor)
        alias.assert_called_once_with("source-copy")
        using.assert_called_once_with("pinned_source")
        query.get.assert_called_once_with(pk=self.actor.pk)
        origin_connection.close.assert_called_once_with()

    def test_origin_runner_access_expires_after_maintenance_generation_changes(self):
        operation = {"actor_id": self.actor.pk, "actor_name": self.actor.username, "actor_database": "source-copy"}
        for state in ({"enabled": False, "generation": self.generation},
                      {"enabled": True, "generation": self.generation + 1}):
            with self.subTest(state=state), \
                    patch.object(service.database_selection, "current_database", return_value="active-copy"), \
                    patch.object(service.database_selection, "read_state", return_value={"maintenance_generation": self.generation}), \
                    patch.object(service, "read_status", return_value=state), \
                    patch.object(service.database_selection, "alias_for_database") as alias:
                with self.assertRaisesMessage(service.TransferError, "previous database"):
                    service._runner_actor(operation)
                alias.assert_not_called()

    def test_runner_rejects_inactive_and_nonadministrator_accounts(self):
        operation = {"actor_id": self.actor.pk, "actor_name": self.actor.username}
        for updates in ({"is_active": False}, {"is_superuser": False, "is_staff": False}):
            with self.subTest(updates=updates):
                get_user_model().objects.filter(pk=self.actor.pk).update(is_active=True, is_superuser=True, is_staff=True)
                get_user_model().objects.filter(pk=self.actor.pk).update(**updates)
                if updates.get("is_superuser") is False:
                    get_user_model().objects.get(pk=self.actor.pk).groups.clear()
                with self.assertRaisesMessage(service.TransferError, "active QC Tool administrator"):
                    service._runner_actor(operation)

    def test_portable_import_receipt_uses_matching_active_account_with_different_numeric_id(self):
        operation = self.queued_import()
        origin = self.origin_actor()
        with patch.object(service, "_runner_actor", return_value=origin):
            self.assertEqual(service.run_operation(operation["id"])["status"], "completed")
        receipt = TransferReceipt.objects.get(operation_id=operation["id"])
        self.assertEqual(receipt.actor_id, self.actor.pk)
        self.assertNotEqual(receipt.actor_id, origin.pk)
        self.assertEqual(receipt.actor_name, self.actor.username)
        self.assertEqual(store.read_operation(operation["id"])["actor_name"], self.actor.username)

    def test_active_import_actor_requires_matching_password_and_active_administrator(self):
        origin = self.origin_actor()
        variants = (
            {"password": "different-encoded-password"}, {"is_active": False},
            {"is_superuser": False, "is_staff": False}, {"username": "renamed-active-operator"},
        )
        original = {"password": self.actor.password, "is_active": True, "is_superuser": True,
                    "is_staff": True, "username": self.actor.username}
        for updates in variants:
            with self.subTest(updates=updates):
                get_user_model().objects.filter(pk=self.actor.pk).update(**original)
                get_user_model().objects.filter(pk=self.actor.pk).update(**updates)
                if updates.get("is_superuser") is False:
                    get_user_model().objects.get(pk=self.actor.pk).groups.clear()
                with self.assertRaisesMessage(service.TransferError, "active database before importing selective records"):
                    service._active_import_actor(origin)

    def test_invalid_active_identity_stops_runner_before_archive_or_artifact_processing(self):
        operation = self.queued_import()
        origin = self.origin_actor()
        original = {"password": self.actor.password, "is_active": True, "is_superuser": True,
                    "is_staff": True, "username": self.actor.username}
        for updates in ({"password": "different-encoded-password"}, {"is_active": False},
                        {"is_superuser": False, "is_staff": False}, {"username": "unrelated-active-account"}):
            with self.subTest(updates=updates):
                get_user_model().objects.filter(pk=self.actor.pk).update(**original)
                get_user_model().objects.filter(pk=self.actor.pk).update(**updates)
                if updates.get("is_superuser") is False:
                    get_user_model().objects.get(pk=self.actor.pk).groups.clear()
                with patch.object(service, "_runner_actor", return_value=origin), \
                        patch.object(service, "_verified") as verified, \
                        patch.object(service, "_begin_artifact_restore") as begin_artifacts, \
                        self.assertLogs(service.logger, level="ERROR"):
                    with self.assertRaisesMessage(service.TransferError, "active database before importing selective records"):
                        service.run_operation(operation["id"])
                verified.assert_not_called()
                begin_artifacts.assert_not_called()
        self.assertFalse(TransferReceipt.objects.exists())
        self.assertFalse(get_user_model().objects.filter(username="identity-imported-user").exists())
