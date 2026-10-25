"""Owned-copy inventory and deletion never target serving or unknown databases."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection as database_connection, connections
from django.test import TransactionTestCase, override_settings

from qc_tool.database import selection
from qc_tool.database.transfers import databases, postgres, service, store
from qc_tool.database.transfers.errors import TransferError
from qc_tool.frontend.dashboard.services import maintenance
from qc_tool.frontend.dashboard.services.maintenance.operations import pin_operation
from qc_tool.frontend.dashboard.services.maintenance.state import file_lock


CONFIG = {"ENGINE": "qc_tool.database.backends.postgresql", "NAME": "inventory_source",
          "HOST": "inventory.internal", "PORT": "5432", "USER": "inventory_owner"}


class DatabaseInventoryTests(TransactionTestCase):
    def setUp(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(override_settings(QC_TOOL_TRANSFER_DIR=directory / "transfers",
            QC_TOOL_MAINTENANCE_DIR=directory / "maintenance", MAINTENANCE_MODE=False,
            QC_TOOL_CONFIGURED_DATABASE=CONFIG))
        self.actor = get_user_model().objects.create_superuser("inventory-admin", "inventory@example.test", "password")
        self.generation = maintenance.enable(self.actor, 0)["generation"]
        maintenance.advance(self.generation)
        self.enterContext(patch.object(databases, "connection", SimpleNamespace(vendor="postgresql")))
        self.cluster = {"params": {"host": CONFIG["HOST"], "port": CONFIG["PORT"]},
                        "owner_oid": 17, "server_major": 14,
                        "databases": [self.row(CONFIG["NAME"], oid=101), self.row("unrelated", oid=102)]}
        self.catalog = self.enterContext(patch.object(databases, "_cluster", side_effect=lambda: deepcopy(self.cluster)))
        self.drop = self.enterContext(patch.object(databases, "_drop"))

    def row(self, name, *, oid=200, marker=None):
        return {"database": name, "oid": oid, "owner_oid": 17, "marker": marker,
                "bytes": 123456, "clients": 0, "prepared_transactions": False,
                "allow_connections": True}

    def operation(self, *, status="completed", kind="import", owner=True):
        operation_id = str(uuid4())
        name = postgres.restore_database_name(operation_id)
        marker = "qc-tool-restore:" + operation_id + ":" + "a" * 64
        operation = {"version": 1, "id": operation_id, "kind": kind, "profile": "database",
                     "status": status, "created_at": store.now(), "updated_at": store.now(),
                     "actor_id": self.actor.pk, "actor_name": self.actor.username,
                     "message": "Restored", "error": "", "plan": None,
                     "result": {"verified": status == "completed", "target_database": name},
                     "destination": {"database": name}, "package_sha256": "b" * 64}
        store.operation_dir(operation_id, create=True)
        store.save_operation(operation)
        if owner:
            fingerprint = postgres._target_fingerprint(self.cluster["params"],
                {"oid": 101, "database": CONFIG["NAME"]},
                {"oid": 0, "database": name, "server_major": 14})
            journal = {"version": 1, "operation_id": operation_id, "database": name,
                       "package_sha256": operation["package_sha256"], "source_fingerprint": fingerprint,
                       "owner_oid": 17, "marker": marker, "status": "ready", "target_oid": 200}
            store.write_json(store.operation_dir(operation_id) / "restore-target.json", journal)
        self.cluster["databases"].append(self.row(name, marker=marker))
        return operation

    def delete(self, operation, **changes):
        return service.delete_restore_database(operation["id"], self.actor,
            **({"generation": self.generation, "revision": selection.read_state()["revision"],
                "destination_confirmation": postgres.restore_database_name(operation["id"])} | changes))

    def entry(self, operation):
        return next(entry for entry in service.database_inventory(self.actor)["databases"]
                    if entry["operation_id"] == operation["id"])

    def test_inventory_distinguishes_active_owned_and_unrelated_without_mutating(self):
        operation = self.operation()
        before = store.read_operation(operation["id"])
        inventory = service.database_inventory(self.actor)
        self.assertEqual(inventory["active_database"], CONFIG["NAME"])
        active = inventory["databases"][0]
        self.assertTrue(active["active"])
        self.assertFalse(active["can_delete"])
        copy = self.entry(operation)
        self.assertTrue(copy["managed"])
        self.assertTrue(copy["can_delete"])
        self.assertTrue(copy["can_review_switch"])
        self.assertEqual(copy["bytes"], 123456)
        unrelated = next(row for row in inventory["databases"] if row["database"] == "unrelated")
        self.assertEqual(unrelated["status"], "external")
        self.assertFalse(unrelated["can_delete"])
        self.assertFalse(unrelated["can_review_selection"])
        self.assertEqual(store.read_operation(operation["id"]), before)
        self.drop.assert_not_called()

    def test_owned_empty_or_failed_destinations_can_be_deleted(self):
        for status in ("staged", "failed"):
            with self.subTest(status=status):
                operation = self.operation(status=status)
                self.assertTrue(self.entry(operation)["can_delete"])
                self.assertFalse(self.entry(operation)["can_review_switch"])

    def test_inventory_and_delete_require_administrator(self):
        user = get_user_model().objects.create_user("inventory-user", password="password")
        operation = self.operation()
        with self.assertRaises(TransferError):
            service.database_inventory(user)
        with self.assertRaises(TransferError):
            service.delete_restore_database(operation["id"], user, generation=self.generation,
                revision=0, destination_confirmation=operation["destination"]["database"])
        self.drop.assert_not_called()

    def test_delete_requires_exact_name_and_current_selection_revision(self):
        operation = self.operation()
        for changes in ({"destination_confirmation": "other"}, {"revision": 1}, {"revision": True}):
            with self.subTest(changes=changes), self.assertRaises(TransferError):
                self.delete(operation, **changes)
        self.drop.assert_not_called()

    def test_delete_requires_ready_maintenance_generation(self):
        operation = self.operation()
        for generation in (None, True, self.generation + 1):
            with self.subTest(generation=generation), self.assertRaises(TransferError):
                self.delete(operation, generation=generation)
        maintenance.disable(self.actor, self.generation)
        self.assertFalse(self.entry(operation)["can_delete"])
        with self.assertRaises(TransferError):
            self.delete(operation)
        self.drop.assert_not_called()

    def test_transfer_execution_or_maintenance_pin_blocks_removal(self):
        operation = self.operation()
        with store.execution_lock():
            self.assertFalse(self.entry(operation)["can_delete"])
            with self.assertRaises(TransferError):
                self.delete(operation)
        with file_lock("control", blocking=False) as acquired:
            self.assertTrue(acquired)
            pin_operation(str(uuid4()), "export", self.generation)
        self.assertFalse(self.entry(operation)["can_delete"])
        with self.assertRaises(TransferError):
            self.delete(operation)
        self.drop.assert_not_called()

    def test_current_and_retained_copies_are_protected(self):
        operation = self.operation()
        name = operation["destination"]["database"]
        for active, previous in ((name, CONFIG["NAME"]), (CONFIG["NAME"], name)):
            with self.subTest(active=active):
                state = selection.read_state()
                state.update(active=active, previous=previous, revision=state["revision"] + 1,
                             changed_at=store.now())
                selection.write_state(state, state["revision"] - 1)
                self.assertFalse(self.entry(operation)["can_delete"])
                with self.assertRaises(TransferError):
                    self.delete(operation)
        self.drop.assert_not_called()

    def test_configured_database_is_protected_even_with_no_retention_pointer(self):
        operation = self.operation()
        with patch.object(databases.postgres, "restore_database_name", return_value=CONFIG["NAME"]):
            with self.assertRaisesMessage(TransferError, "configured database"):
                self.delete(operation, destination_confirmation=CONFIG["NAME"])
        self.drop.assert_not_called()

    def test_name_alone_without_private_ownership_never_authorizes_delete(self):
        operation = self.operation(owner=False)
        self.assertFalse(self.entry(operation)["managed"])
        with self.assertRaises(TransferError):
            self.delete(operation)
        self.drop.assert_not_called()

    def test_oid_marker_owner_and_source_cluster_changes_are_refused(self):
        operation = self.operation()
        row = self.cluster["databases"][-1]
        for key, value in (("oid", 999), ("marker", "replacement"), ("owner_oid", 99)):
            original = row[key]
            row[key] = value
            with self.subTest(key=key), self.assertRaises(TransferError):
                self.delete(operation)
            row[key] = original
        self.cluster["params"]["host"] = "another-cluster"
        with self.assertRaises(TransferError):
            self.delete(operation)
        self.drop.assert_not_called()

    def test_createdb_gap_or_recreated_source_never_authorizes_delete(self):
        operation = self.operation()
        self.cluster["databases"][0]["oid"] = 555
        with self.assertRaises(TransferError):
            self.delete(operation)
        self.cluster["databases"][0]["oid"] = 101
        path = store.operation_dir(operation["id"]) / "restore-target.json"
        journal = store.read_json(path)
        journal.update(status="creating", target_oid=None)
        store.write_json(path, journal)
        with self.assertRaises(TransferError):
            self.delete(operation)
        self.drop.assert_not_called()

    def test_other_clients_or_prepared_transactions_block_deletion(self):
        operation = self.operation()
        row = self.cluster["databases"][-1]
        for key in ("clients", "prepared_transactions"):
            row[key] = 1
            self.assertFalse(self.entry(operation)["can_delete"])
            with self.assertRaises(TransferError):
                self.delete(operation)
            row[key] = 0
        self.drop.assert_not_called()

    def test_source_copy_is_retained_until_its_managed_children_are_removed(self):
        parent = self.operation()
        child = self.operation()
        child_path = store.operation_dir(child["id"]) / "restore-target.json"
        journal = store.read_json(child_path)
        self.cluster["databases"][-1]["oid"] = 201
        journal.update(target_oid=201, source_fingerprint=postgres._target_fingerprint(
            self.cluster["params"], {"database": parent["destination"]["database"], "oid": 200},
            {"database": child["destination"]["database"], "oid": 0, "server_major": 14}))
        store.write_json(child_path, journal)
        row = self.entry(parent)
        self.assertFalse(row["can_delete"])
        self.assertEqual(row["dependent_databases"], [child["destination"]["database"]])
        with self.assertRaisesMessage(TransferError, "depend on its original identity"):
            self.delete(parent)
        self.drop.assert_not_called()
        self.assertTrue(self.entry(child)["can_delete"])
        self.delete(child)
        self.cluster["databases"].pop()
        self.assertTrue(self.entry(parent)["can_delete"])
        self.assertTrue(self.delete(parent)["deleted"])

    def test_successful_delete_retains_operation_package_and_private_audit(self):
        operation = self.operation()
        path = store.operation_dir(operation["id"])
        (path / "package.zip").write_bytes(b"retained recovery package")
        result = self.delete(operation)
        self.assertTrue(result["deleted"])
        self.drop.assert_called_once()
        audit = store.read_json(path / "database-deletion.json")
        self.assertEqual(audit["status"], "completed")
        self.assertEqual(audit["requested_by"], self.actor.username)
        self.assertEqual((path / "database-deletion.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual((path / "package.zip").read_bytes(), b"retained recovery package")
        self.assertEqual(store.read_operation(operation["id"])["status"], "completed")
        self.assertTrue(store.read_operation(operation["id"])["database_deleted_at"])

    def test_lost_drop_acknowledgement_recovers_without_dropping_twice(self):
        operation = self.operation()
        def lost_ack(_identity, _params):
            self.cluster["databases"].pop()
            raise TransferError("Lost acknowledgement")
        self.drop.side_effect = lost_ack
        with self.assertRaises(TransferError):
            self.delete(operation)
        self.assertEqual(databases._deletion(operation)["status"], "requested")
        self.assertTrue(self.entry(operation)["can_complete_deletion"])
        self.assertTrue(self.entry(operation)["can_delete"])
        self.assertTrue(self.delete(operation)["deleted"])
        self.assertEqual(self.drop.call_count, 1)
        self.assertEqual(databases._deletion(operation)["status"], "completed")

    def test_completed_tombstone_cannot_delete_or_select_replacement(self):
        operation = self.operation()
        self.delete(operation)
        self.cluster["databases"][-1]["oid"] = 999
        with self.assertRaisesMessage(TransferError, "replacement database"):
            self.delete(operation)
        copy = self.entry(operation)
        self.assertFalse(copy["can_delete"])
        self.assertFalse(copy["can_review_selection"])
        self.assertFalse(copy["can_review_switch"])
        self.assertEqual(self.drop.call_count, 1)

    def test_lost_drop_acknowledgement_cannot_complete_on_another_cluster(self):
        operation = self.operation()
        self.drop.side_effect = TransferError("Lost acknowledgement")
        with self.assertRaises(TransferError):
            self.delete(operation)
        self.cluster["databases"].pop()
        self.cluster["params"]["host"] = "another-cluster"
        with self.assertRaises(TransferError):
            self.delete(operation)
        self.assertEqual(databases._deletion(operation)["status"], "requested")

    def test_missing_selected_database_still_has_an_explanatory_entry(self):
        self.cluster["databases"].pop(0)
        row = service.database_inventory(self.actor)["databases"][0]
        self.assertTrue(row["active"])
        self.assertFalse(row["present"])
        self.assertEqual(row["label"], "Database unavailable")
        self.assertFalse(row["can_delete"])

    def test_inspection_rejects_unrelated_names_before_connecting(self):
        with patch.object(databases.selection, "alias_for_database") as alias:
            with self.assertRaises(TransferError):
                service.database_details("unrelated", self.actor)
        alias.assert_not_called()

    def test_inspection_refuses_replaced_previous_database_before_connecting(self):
        state = selection.read_state()
        state.update(previous="unrelated", revision=1, changed_at=store.now(),
                     activation={"source_native": {"oid": 999}})
        selection.write_state(state, 0)
        with patch.object(databases.selection, "alias_for_database") as alias:
            with self.assertRaisesMessage(TransferError, "recorded identity"):
                service.database_details("unrelated", self.actor)
        alias.assert_not_called()

    def test_default_alias_inspection_restores_previous_timeout(self):
        inspected = MagicMock()
        cursor = inspected.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [("45s",), (101,)]
        cursor.fetchmany.side_effect = [[("public", "sample", None, 1024)], []]
        with patch.object(databases.selection, "alias_for_database", return_value="default"), \
                patch.object(databases, "connections", {"default": inspected}), \
                patch.object(databases, "SchemaInitializer"):
            details = service.database_details(CONFIG["NAME"], self.actor)
        self.assertIsNone(details["estimated_rows"])
        self.assertEqual(details["table_count"], 1)
        cursor.execute.assert_any_call("SELECT set_config('statement_timeout', %s, false)", ["45s"])
        inspected.close.assert_not_called()

    def test_default_alias_timeout_is_restored_after_inspection_error(self):
        inspected = MagicMock()
        cursor = inspected.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [("45s",), (101,)]
        cursor.fetchmany.side_effect = DatabaseError("private diagnostic")
        with patch.object(databases.selection, "alias_for_database", return_value="default"), \
                patch.object(databases, "connections", {"default": inspected}):
            with self.assertRaises(TransferError) as raised:
                service.database_details(CONFIG["NAME"], self.actor)
        self.assertNotIn("private diagnostic", str(raised.exception))
        cursor.execute.assert_any_call("SELECT set_config('statement_timeout', %s, false)", ["45s"])

    def test_managed_identity_survives_selection_of_another_database(self):
        operation = self.operation()
        before = databases.managed_identity(operation)
        state = selection.read_state()
        state.update(active="unrelated", previous=CONFIG["NAME"], revision=1, changed_at=store.now())
        selection.write_state(state, 0)
        self.assertEqual(databases.managed_identity(operation), before)


@skipUnless(database_connection.vendor == "postgresql", "Native PostgreSQL management")
class PostgreSQLDatabaseInventoryTests(TransactionTestCase):
    """DDL is restricted to names generated and created by this test instance."""

    def setUp(self):
        from psycopg2 import sql

        self.assertTrue(database_connection.settings_dict["NAME"].startswith("test_"))
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(override_settings(QC_TOOL_TRANSFER_DIR=directory / "transfers",
            QC_TOOL_MAINTENANCE_DIR=directory / "maintenance", MAINTENANCE_MODE=False,
            QC_TOOL_CONFIGURED_DATABASE=deepcopy(database_connection.settings_dict)))
        self.actor = get_user_model().objects.create_superuser("real-inventory-admin", "real@example.test", "password")
        self.generation = maintenance.enable(self.actor, 0)["generation"]
        maintenance.advance(self.generation)
        operation_id = str(uuid4())
        self.name = postgres.restore_database_name(operation_id)
        self.marker = "qc-tool-restore:" + operation_id + ":" + "c" * 64
        self.operation = {"version": 1, "id": operation_id, "kind": "import", "profile": "database",
                          "status": "planned", "created_at": store.now(), "updated_at": store.now(),
                          "actor_id": self.actor.pk, "actor_name": self.actor.username,
                          "message": "Prepared empty test copy", "error": "", "plan": None,
                          "result": {}, "destination": {"database": self.name}, "package_sha256": "d" * 64}
        with database_connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(self.name)))
            cursor.execute(sql.SQL("COMMENT ON DATABASE {} IS {}").format(sql.Identifier(self.name), sql.Literal(self.marker)))
        self.addCleanup(self.remove_test_database)
        cluster = databases._cluster()
        source = next(row for row in cluster["databases"] if row["database"] == database_connection.settings_dict["NAME"])
        target = next(row for row in cluster["databases"] if row["database"] == self.name)
        store.operation_dir(operation_id, create=True)
        store.save_operation(self.operation)
        store.write_json(store.operation_dir(operation_id) / "restore-target.json", {
            "version": 1, "operation_id": operation_id, "database": self.name,
            "package_sha256": self.operation["package_sha256"],
            "source_fingerprint": postgres._target_fingerprint(cluster["params"], source,
                {"database": self.name, "oid": 0, "server_major": cluster["server_major"]}),
            "owner_oid": cluster["owner_oid"], "marker": self.marker,
            "status": "ready", "target_oid": target["oid"],
        })

    def remove_test_database(self):
        from psycopg2 import sql

        self.assertRegex(self.name, r"\Aqc_restore_[0-9a-f]{32}\Z")
        with database_connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(self.name)))

    def remove(self):
        return service.delete_restore_database(self.operation["id"], self.actor,
            generation=self.generation, revision=0, destination_confirmation=self.name)

    def exists(self):
        with database_connection.cursor() as cursor:
            cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname=%s)", [self.name])
            return cursor.fetchone()[0]

    def test_real_owned_database_drop_preserves_source_and_audit(self):
        before = get_user_model().objects.count()
        inventory = service.database_inventory(self.actor)
        row = next(row for row in inventory["databases"] if row["database"] == self.name)
        self.assertTrue(row["can_delete"])
        self.assertGreater(row["bytes"], 0)
        self.assertTrue(self.remove()["deleted"])
        self.assertFalse(self.exists())
        self.assertEqual(get_user_model().objects.count(), before)
        self.assertEqual(databases._deletion(self.operation)["status"], "completed")
        self.assertTrue(self.remove()["deleted"])

    def test_real_connected_client_is_preserved_without_force(self):
        import psycopg2

        target = psycopg2.connect(**{**postgres._params(), "dbname": self.name})
        try:
            with self.assertRaisesMessage(TransferError, "using this copy"):
                self.remove()
            self.assertTrue(self.exists())
            with target.cursor() as cursor:
                cursor.execute("SELECT current_database()")
                self.assertEqual(cursor.fetchone()[0], self.name)
        finally:
            target.close()

    def test_real_marker_change_protects_database(self):
        from psycopg2 import sql

        with database_connection.cursor() as cursor:
            cursor.execute(sql.SQL("COMMENT ON DATABASE {} IS 'different-owner'").format(sql.Identifier(self.name)))
        with self.assertRaisesMessage(TransferError, "identity or ownership changed"):
            self.remove()
        self.assertTrue(self.exists())

    def test_real_inspection_reports_schema_and_catalog_without_initialization(self):
        alias = selection.alias_for_database(self.name)
        allowed = type(self).databases
        type(self).databases = allowed | {alias}
        try:
            details = service.database_details(self.name, self.actor)
            self.assertEqual(details["database"], self.name)
            self.assertEqual(details["table_count"], 0)
            self.assertFalse(details["schema"]["ready"])
            self.assertTrue(details["counts_are_estimates"])
            self.assertTrue(self.exists())
        finally:
            connections[alias].close()
            del connections[alias]
            connections.databases.pop(alias, None)
            type(self).databases = allowed
