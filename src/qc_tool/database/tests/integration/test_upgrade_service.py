"""Native migration upgrades touch only disposable operation-owned copies."""

from pathlib import Path
from datetime import datetime
from io import StringIO
import shutil
import sys
from tempfile import TemporaryDirectory
from unittest import skipUnless
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import connection, connections, models
from django.db.migrations.recorder import MigrationRecorder
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse

from qc_tool.database import migration_engine, selection
from qc_tool.database.tests.integration import test_database_control as fixtures
from qc_tool.database.transfers import control, postgres, service as transfers, store
from qc_tool.database.transfers import records
from qc_tool.database.transfers.components import FILE_COMPONENTS
from qc_tool.database.transfers.errors import TransferError
from qc_tool.database.upgrades import connections as upgrade_connections
from qc_tool.database.upgrades import service as upgrades
from qc_tool.frontend.dashboard.services.maintenance.operations import active_operation
from qc_tool.frontend.dashboard.services.maintenance.state import read_status


@skipUnless(connection.vendor == "postgresql", "Upgrade orchestration requires disposable PostgreSQL")
@override_settings(PASSWORD_HASHERS=("django.contrib.auth.hashers.MD5PasswordHasher",),
                   QC_TOOL_TRANSFER_MIN_FREE_BYTES=1024**2, QC_TOOL_RESTORE_DATABASE="", MAINTENANCE_MODE=False)
class PostgreSQLUpgradeServiceTests(TransactionTestCase):
    """Reuse native control fixtures without inheriting their unrelated tests."""

    password = fixtures.PostgreSQLDatabaseControlTests.password
    allow_alias = fixtures.PostgreSQLDatabaseControlTests.allow_alias
    add_report = fixtures.PostgreSQLDatabaseControlTests.add_report
    no_model_writes = fixtures.PostgreSQLDatabaseControlTests.no_model_writes
    activate = fixtures.PostgreSQLDatabaseControlTests.activate
    external_user_change = fixtures.PostgreSQLDatabaseControlTests.external_user_change

    def setUp(self):
        fixtures.PostgreSQLDatabaseControlTests.setUp(self)
        self.original_history = None

    def tearDown(self):
        # Restore only the disposable test DB's recorder for Django's next test.
        # The original deployment has never been connected or modified.
        (self.root / "transfers" / "database-selection.json").unlink(missing_ok=True)
        connection.close()
        if self.original_history is not None:
            with connection.cursor() as cursor:
                for table in ("auth_group_permissions", "auth_user_groups", "auth_user_user_permissions"):
                    cursor.execute(f'ALTER TABLE "{table}" ALTER COLUMN id TYPE integer')
                    cursor.execute(f'ALTER SEQUENCE "{table}_id_seq" AS integer')
            recorder = MigrationRecorder(connection)
            recorder.ensure_schema()
            for app, name in self.original_history:
                recorder.record_applied(app, name)
        for alias in self.used_aliases:
            if alias in connections:
                connections[alias].close()
                if alias not in self.original_aliases:
                    del connections[alias]
                    connections.databases.pop(alias, None)
        type(self).databases = self.original_allowed_databases
        from psycopg2 import sql
        with connection.cursor() as cursor:
            for name in self.targets:
                self.assertRegex(name, r"\Aqc_restore_[0-9a-f]{32}\Z")
                cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
        super().tearDown()

    def legacy_backup(self, *, legacy_storage=False, auth_join_bigint=True):
        self.report_path = self.add_report()
        self.original_report = self.report_path.read_bytes()
        self.original_password = self.actor.password
        # Existing managed-group overrides are business data too. Adoption
        # should not fire an otherwise unnecessary post_migrate bootstrap.
        Group.objects.get(name=fixtures.Role.ADMIN.value).permissions.clear()
        self.original_group_grants = list(Group.permissions.through.objects.order_by("pk").values())
        self.extra_files = {}
        if legacy_storage:
            self.extra_files = {
                fixtures.CONFIG["work_dir"] / "product_definitions/fixture-product.json": b'{"synthetic":"original specification"}\\n',
                fixtures.CONFIG["boundary_dir"] / "vector/fixture.gpkg": b"synthetic original boundary bytes",
            }
            for path, original in self.extra_files.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(original)
        self.original_history = sorted(MigrationRecorder(connection).applied_migrations())
        self.assertTrue(self.source.startswith("test_"))
        with connection.cursor() as cursor:
            # History-free installations can retain Django's integer join IDs
            # or application-generated bigint IDs. Exercise both supported
            # variants without narrowing any stored IDs during adoption.
            if auth_join_bigint:
                for table in ("auth_group_permissions", "auth_user_groups", "auth_user_user_permissions"):
                    cursor.execute(f'ALTER TABLE "{table}" ALTER COLUMN id TYPE bigint')
                    cursor.execute(f'ALTER SEQUENCE "{table}_id_seq" AS bigint')
            cursor.execute("DROP TABLE django_migrations")
        self.assertEqual(migration_engine.migration_status(connection)["state"], "legacy")
        self.source_before = postgres.preview()
        scope = {"profile": "database", "user_ids": [], "components": list(FILE_COMPONENTS)}
        review = transfers.export_preview(scope, self.actor)
        backup = transfers.create_export(scope, self.actor, review["review_hash"], self.generation)
        self.assertEqual(transfers.run_operation(backup["id"])["status"], "completed")
        return backup

    def start_upgrade(self, backup):
        review = upgrades.preview(backup["id"], self.actor)
        self.assertTrue(review["can_apply"], review["blockers"])
        queued = upgrades.start(backup["id"], self.actor, review["review_hash"], self.generation, review["revision"])
        name = postgres.restore_database_name(queued["id"])
        self.targets.add(name)
        self.allow_alias(name)
        writable = "qc_upgrade_" + queued["id"].replace("-", "")
        type(self).databases = frozenset((*type(self).databases, writable))
        self.used_aliases.add(writable)
        return queued, name

    def assert_source_retained(self):
        self.assertEqual(selection.current_database(), self.source)
        self.assertNotIn("django_migrations", connection.introspection.table_names())
        self.assertEqual(postgres.preview()["review_hash"], self.source_before["review_hash"])
        self.assertEqual(self.report_path.read_bytes(), self.original_report)
        self.assertEqual(self.actor.password, self.original_password)
        self.assertEqual(list(Group.permissions.through.objects.order_by("pk").values()), self.original_group_grants)
        for path, original in self.extra_files.items():
            self.assertEqual(path.read_bytes(), original)
        self.assertTrue(read_status()["enabled"])

    def test_status_reads_recorder_dates_without_writes_or_changing_plan_identity(self):
        recorder = MigrationRecorder(connection)
        # QC Tool currently uses USE_TZ=False; preserve the recorder's local
        # timestamp and let the shared presentation helper localize it.
        recorded_at = datetime(2026, 11, 6, 12, 34, 56)
        self.assertEqual(recorder.migration_qs.filter(app="dashboard", name="0001_initial").update(
            applied=recorded_at), 1)
        original = self.no_model_writes(lambda: upgrade_connections.inspect_migrations(self.source))
        self.assertNotIn("applied_history", original)
        overview = self.no_model_writes(lambda: upgrades.status(self.actor))
        self.assertEqual(overview["database"]["plan_hash"], original["plan_hash"])
        self.assertIn({"app": "dashboard", "name": "0001_initial",
                       "applied_at": recorded_at.isoformat()}, overview["database"]["applied_history"])
        self.assertEqual(self.no_model_writes(lambda: upgrade_connections.inspect_migrations(self.source)), original)

    def test_history_free_status_does_not_create_a_migration_recorder(self):
        self.original_history = sorted(MigrationRecorder(connection).applied_migrations())
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE django_migrations")
        overview = self.no_model_writes(lambda: upgrades.status(self.actor))
        self.assertEqual(overview["database"]["state"], "legacy")
        self.assertEqual(overview["database"]["applied_history"], [])
        self.assertFalse(MigrationRecorder(connection).has_table())

    def test_models_only_copy_migrates_and_switches_without_source_or_file_mutation(self):
        backup = self.legacy_backup()
        queued, target = self.start_upgrade(backup)
        completed = transfers.run_operation(queued["id"])
        self.assertEqual(completed["status"], "completed")
        self.assertIsNone(active_operation())
        self.assert_source_retained()
        alias = self.allow_alias(target)
        self.assertEqual(migration_engine.migration_status(connections[alias])["state"], "ready")
        connections[alias].close()
        directory = store.operation_dir(queued["id"])
        self.assertTrue((directory / "migration-completed.json").is_file())
        self.assertTrue((directory / "storage-pin.json").is_file())
        self.assertTrue(store.package_path(backup["id"]).is_file())
        preview = self.no_model_writes(lambda: transfers.activation_preview(queued["id"], self.actor))
        self.assertTrue(preview["can_apply"])
        self.no_model_writes(lambda: self.activate(completed, target, preview))
        self.assertEqual(selection.current_database(), target)
        self.assertEqual(selection.read_state()["previous"], self.source)
        self.assertEqual(self.report_path.read_bytes(), self.original_report)
        blockers = control.status(self.actor)["rollback_blockers"]
        self.assertTrue(any("previous pinned application images" in item for item in blockers))

    def test_integer_auth_join_source_adopts_without_changing_integer_widths(self):
        backup = self.legacy_backup(auth_join_bigint=False)
        queued, target = self.start_upgrade(backup)
        self.assertEqual(transfers.run_operation(queued["id"])["status"], "completed")
        self.assert_source_retained()
        with selection.database_scope(target), connection.cursor() as cursor:
            cursor.execute("""SELECT c.relname, format_type(a.atttypid,a.atttypmod)
                FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
                WHERE c.relname IN ('auth_group_permissions','auth_user_groups','auth_user_user_permissions')
                  AND a.attname='id' ORDER BY c.relname""")
            self.assertEqual([datatype for _table, datatype in cursor.fetchall()], ["integer"] * 3)

    def test_candidate_inherits_django_defaults_with_sparse_operator_database_settings(self):
        backup = self.legacy_backup(auth_join_bigint=False)
        raw = {key: value for key, value in connection.settings_dict.items()
               if key in {"ENGINE", "NAME", "HOST", "PORT", "USER", "PASSWORD", "OPTIONS"}}
        self.assertNotIn("TIME_ZONE", raw)
        with override_settings(QC_TOOL_CONFIGURED_DATABASE=raw):
            queued, _target = self.start_upgrade(backup)
            self.assertEqual(transfers.run_operation(queued["id"])["status"], "completed")
        self.assert_source_retained()

    def test_admin_http_journey_reviews_runs_and_selects_the_verified_copy(self):
        """Exercise actual forms/authentication and services with a real PG copy."""
        backup = self.legacy_backup()
        client = Client(enforce_csrf_checks=True)
        url = reverse("admin_migrations")
        login_url = reverse("admin:login")
        page = self.no_model_writes(lambda: client.get(login_url))
        signed_in = self.no_model_writes(lambda: client.post(login_url, {
            "username": self.actor.username, "password": self.password, "next": url,
        }, HTTP_X_CSRFTOKEN=str(page.context["csrf_token"])))
        self.assertEqual(signed_in.status_code, 302)

        def submit(payload):
            current = client.get(url)
            self.assertEqual(current.status_code, 200)
            return client.post(url, payload, HTTP_X_CSRFTOKEN=str(current.context["csrf_token"]))

        reviewed = self.no_model_writes(lambda: submit({"action": "review", "backup_id": backup["id"]}))
        self.assertEqual(reviewed.status_code, 200)
        review = reviewed.context["migration_review"]
        self.assertEqual(len(review["storage_areas"]), 5)
        prepared = submit({"action": "start", "backup_id": backup["id"], "confirmed_backup": "on",
                           **{key: review[key] for key in ("review_hash", "generation", "revision")}})
        self.assertEqual(prepared.status_code, 303)
        operation_id = parse_qs(urlsplit(prepared.url).query)["operation"][0]
        target = postgres.restore_database_name(operation_id)
        self.targets.add(target)
        self.allow_alias(target)
        writable = "qc_upgrade_" + operation_id.replace("-", "")
        type(self).databases = frozenset((*type(self).databases, writable))
        self.used_aliases.add(writable)
        self.assertEqual(transfers.run_operation(operation_id)["status"], "completed")
        self.assert_source_retained()
        confirmation = self.no_model_writes(lambda: submit({"action": "review_switch", "operation_id": operation_id}))
        self.assertEqual(confirmation.status_code, 200)
        activation = confirmation.context["activation_review"]
        selected = self.no_model_writes(lambda: submit({"action": "activate", "operation_id": operation_id,
            "activation-review_hash": activation["review_hash"], "activation-revision": activation["revision"],
            "activation-generation": self.generation, "activation-destination_confirmation": target,
            "activation-confirmed_storage": "on"}))
        self.assertEqual(selected.status_code, 303)
        self.assertEqual(selection.current_database(), target)
        self.assertTrue(read_status()["enabled"])
        active_page = self.no_model_writes(lambda: client.get(selected.url))
        self.assertEqual(active_page.status_code, 200)
        self.assertTrue(active_page.context["operation_active"])
        with selection.database_scope(self.source):
            self.assertNotIn("django_migrations", connection.introspection.table_names())
            self.assertEqual(postgres.preview()["review_hash"], self.source_before["review_hash"])

    def test_managed_postgresql_source_upgrades_schema_and_data_on_candidate_before_switch(self):
        self.future_managed_upgrade()

    def test_future_migration_cannot_introduce_missing_retained_file_references(self):
        self.future_managed_upgrade(introduce_missing_reference=True)

    def future_managed_upgrade(self, *, introduce_missing_reference=False):
        """A future installed graph can change SQL while the old source stays live."""
        Product = fixtures.Delivery._meta.apps.get_model("dashboard", "Product")
        product = Product.objects.create(ident="forward-product", name="Before PostgreSQL upgrade")
        report_path = self.add_report()
        original_report = report_path.read_bytes()
        field_name = "future_upgrade_probe"
        with TemporaryDirectory(prefix="qc-pg-forward-release-") as temporary:
            package = Path(temporary) / ("pg_forward_history_" + uuid4().hex)
            package.mkdir()
            (package / "__init__.py").touch()
            initial = Path(__file__).resolve().parents[3] / "frontend/dashboard/migrations/0001_initial.py"
            shutil.copyfile(initial, package / "0001_initial.py")
            (package / "0002_postgresql_forward_probe.py").write_text(
                "from django.db import migrations, models\n"
                "def forwards(apps, schema_editor):\n"
                "    apps.get_model('dashboard', 'Product').objects.using(schema_editor.connection.alias).filter(ident='forward-product').update(name='After PostgreSQL upgrade')\n"
                + ("    Delivery = apps.get_model('dashboard', 'Delivery')\n"
                   "    owner = Delivery.objects.using(schema_editor.connection.alias).first().user_id\n"
                   "    Delivery.objects.using(schema_editor.connection.alias).create(user_id=owner, filename='missing-from-storage.zip', size_bytes=1, content_sha256='" + "a" * 64 + "')\n"
                   if introduce_missing_reference else "")
                +
                "class Migration(migrations.Migration):\n"
                "    dependencies = [('dashboard', '0001_initial')]\n"
                "    operations = [migrations.AddField('product', 'future_upgrade_probe', models.CharField(max_length=32, default='retained')), migrations.RunPython(forwards, migrations.RunPython.noop)]\n"
            )
            field = models.CharField(max_length=32, default="retained")
            Product.add_to_class(field_name, field)
            sys.path.insert(0, temporary)
            try:
                # A real release updates its explicit portable field registry
                # with its model; native source backup itself remains ORM-free.
                model, fields = records.RESOURCE_FIELDS["products"]
                with override_settings(MIGRATION_MODULES={"dashboard": package.name}), patch.dict(
                        records.RESOURCE_FIELDS, {"products": (model, (*fields, field_name))}):
                    source_status = migration_engine.migration_status(connection)
                    self.assertEqual(source_status["state"], "pending", source_status["problems"])
                    self.assertEqual(source_status["pending"][0]["name"], "0002_postgresql_forward_probe")
                    self.assertEqual(control._application_snapshot(self.source, allow_legacy=True)["schema_mode"], "pending")
                    source_inventory = postgres.preview()["review_hash"]
                    scope = {"profile": "database", "user_ids": [], "components": list(FILE_COMPONENTS)}
                    review = transfers.export_preview(scope, self.actor)
                    backup = transfers.create_export(scope, self.actor, review["review_hash"], self.generation)
                    self.assertEqual(transfers.run_operation(backup["id"])["status"], "completed")
                    queued, target = self.start_upgrade(backup)
                    if introduce_missing_reference:
                        with self.assertRaisesMessage(TransferError, "introduces unavailable file references"):
                            transfers.run_operation(queued["id"])
                        operation = store.read_operation(queued["id"])
                        self.assertEqual(operation["status"], "recovery_required")
                        self.assertTrue(operation["migration_started"])
                        self.assertFalse((store.operation_dir(queued["id"]) / "migration-completed.json").exists())
                        self.assertEqual(active_operation()["operation_id"], queued["id"])
                        self.assertEqual(selection.current_database(), self.source)
                        self.assertEqual(postgres.preview()["review_hash"], source_inventory)
                        self.assertEqual(report_path.read_bytes(), original_report)
                        self.assertTrue(read_status()["enabled"])
                        return
                    completed = transfers.run_operation(queued["id"])
                    self.assertEqual(completed["status"], "completed")
                    self.assertEqual(selection.current_database(), self.source)
                    self.assertEqual(postgres.preview()["review_hash"], source_inventory)
                    with connection.cursor() as cursor:
                        columns = {item.name for item in connection.introspection.get_table_description(cursor, "catalog_product")}
                        cursor.execute("SELECT name FROM catalog_product WHERE id=%s", [product.pk])
                        self.assertEqual(cursor.fetchone(), ("Before PostgreSQL upgrade",))
                    self.assertNotIn(field_name, columns)
                    self.assertNotIn(("dashboard", "0002_postgresql_forward_probe"), MigrationRecorder(connection).applied_migrations())
                    alias = self.allow_alias(target)
                    candidate = connections[alias]
                    with candidate.cursor() as cursor:
                        columns = {item.name for item in candidate.introspection.get_table_description(cursor, "catalog_product")}
                        cursor.execute("SELECT name,future_upgrade_probe FROM catalog_product WHERE id=%s", [product.pk])
                        self.assertEqual(cursor.fetchone(), ("After PostgreSQL upgrade", "retained"))
                    self.assertIn(field_name, columns)
                    self.assertIn(("dashboard", "0002_postgresql_forward_probe"), MigrationRecorder(candidate).applied_migrations())
                    self.assertEqual(migration_engine.migration_status(candidate)["state"], "ready")
                    candidate.close()
                    directory = store.operation_dir(queued["id"])
                    self.assertTrue((directory / "migration-completed.json").is_file())
                    self.assertTrue((directory / "storage-pin.json").is_file())
                    self.assertEqual(report_path.read_bytes(), original_report)
                    activation = transfers.activation_preview(queued["id"], self.actor)
                    self.assertTrue(activation["can_apply"])
                    self.activate(completed, target, activation)
                    self.assertEqual(selection.current_database(), target)
                    self.assertEqual(selection.read_state()["previous"], self.source)
                    self.assertEqual(report_path.read_bytes(), original_report)
                    self.assertTrue(read_status()["enabled"])
            finally:
                sys.path.remove(temporary)
                Product._meta.local_fields.remove(field)
                delattr(Product, field.attname)
                Product._meta._expire_cache()
                for name in tuple(sys.modules):
                    if name == package.name or name.startswith(package.name + "."):
                        del sys.modules[name]

    def test_upgrade_keeps_flat_specifications_and_legacy_boundary_paths_in_place(self):
        backup = self.legacy_backup(legacy_storage=True)
        before = {str(path.relative_to(self.root)): path.read_bytes() for path in self.extra_files}
        queued, _target = self.start_upgrade(backup)
        self.assertEqual(transfers.run_operation(queued["id"])["status"], "completed")
        self.assert_source_retained()
        self.assertEqual({str(path.relative_to(self.root)): path.read_bytes() for path in self.extra_files}, before)
        self.assertFalse((fixtures.CONFIG["work_dir"] / "product_definitions/.versions").exists())
        self.assertFalse((fixtures.CONFIG["boundary_dir"] / ".boundary-generations").exists())

    def test_upgrade_handles_product_directory_alias_of_original_specification_storage(self):
        specifications = fixtures.CONFIG["work_dir"] / "product_definitions"
        with patch.dict(fixtures.CONFIG, {"product_dirs": [specifications]}):
            backup = self.legacy_backup(legacy_storage=True)
            queued, _target = self.start_upgrade(backup)
            self.assertEqual(transfers.run_operation(queued["id"])["status"], "completed")
            self.assert_source_retained()
            pin = store.read_json(store.operation_dir(queued["id"]) / "storage-pin.json")
            original = specifications / "fixture-product.json"
            protected = [entry for entry in pin["files"]
                         if Path(pin["roots"][entry["root"]]) / entry["key"] == original]
            self.assertEqual(len(protected), 1)
            self.assertEqual(original.read_bytes(), self.extra_files[original])
            self.assertFalse((specifications / ".versions").exists())

    def test_changed_staged_package_blocks_first_activation_of_completed_upgrade(self):
        backup = self.legacy_backup()
        queued, _target = self.start_upgrade(backup)
        self.assertEqual(transfers.run_operation(queued["id"])["status"], "completed")
        with store.package_path(queued["id"]).open("ab") as package:
            package.write(b"changed after completion")
        with self.assertRaises(TransferError):
            transfers.activation_preview(queued["id"], self.actor)
        self.assert_source_retained()
        self.assertFalse((store.operation_dir(queued["id"]) / "database-activation.json").exists())

    def test_changed_candidate_rows_invalidate_completion_evidence_before_first_activation(self):
        backup = self.legacy_backup()
        queued, target = self.start_upgrade(backup)
        self.assertEqual(transfers.run_operation(queued["id"])["status"], "completed")
        self.external_user_change(target, "first_name", "changed candidate")
        with self.assertRaisesMessage(TransferError, "candidate data or physical identity changed"):
            transfers.activation_preview(queued["id"], self.actor)
        self.assert_source_retained()

    def test_changed_source_after_completion_blocks_first_activation(self):
        backup = self.legacy_backup()
        queued, _target = self.start_upgrade(backup)
        self.assertEqual(transfers.run_operation(queued["id"])["status"], "completed")
        self.external_user_change(self.source, "first_name", "changed source")
        with self.assertRaisesMessage(TransferError, "source database changed"):
            transfers.activation_preview(queued["id"], self.actor)
        self.assertEqual(selection.current_database(), self.source)
        self.assertTrue(read_status()["enabled"])
        self.assertFalse((store.operation_dir(queued["id"]) / "database-activation.json").exists())

    def test_unavailable_selected_upgrade_keeps_readonly_recovery_on_legacy_original(self):
        backup = self.legacy_backup()
        queued, target = self.start_upgrade(backup)
        completed = transfers.run_operation(queued["id"])
        self.activate(completed, target)
        connection.close()
        for alias in self.used_aliases:
            if alias in connections:
                connections[alias].close()
        from psycopg2 import sql
        with selection.database_scope(self.source):
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS false").format(sql.Identifier(target)))
        connection.close()
        output = StringIO()
        call_command("database", "check", allow_maintenance_recovery=True, stdout=output, stderr=StringIO())
        self.assertEqual(output.getvalue().strip(), "maintenance-recovery")
        self.assertEqual(selection.read_state()["active"], target)
        self.assertEqual(selection.read_state()["previous"], self.source)
        with selection.database_scope(self.source):
            self.assertNotIn("django_migrations", connection.introspection.table_names())
            self.assertEqual(postgres.preview()["review_hash"], self.source_before["review_hash"])
        self.assertEqual(self.report_path.read_bytes(), self.original_report)
        self.assertTrue(read_status()["enabled"])

        # The administrator must still see the retained operation and concrete
        # availability blocker through the real recovery authentication path.
        client = Client()
        signed_in = client.post(reverse("admin:login"), {
            "username": self.actor.username, "password": self.password,
        })
        self.assertEqual(signed_in.status_code, 302)
        overview = client.get(reverse("admin_migrations"), {"operation": queued["id"]})
        self.assertEqual(overview.status_code, 200)
        self.assertEqual(overview.context["migration_database"]["state"], "unavailable")
        self.assertEqual(overview.context["operation"]["id"], queued["id"])
        self.assertFalse(overview.context["operation"]["can_retry"])
        self.assertFalse(overview.context["operation"]["can_abandon"])

    def test_interrupted_unreceipted_migration_is_not_replayed_or_erased(self):
        backup = self.legacy_backup()
        queued, target = self.start_upgrade(backup)
        with patch.object(migration_engine, "apply_candidate", side_effect=RuntimeError("simulated process loss")) as apply:
            with self.assertRaises(TransferError):
                transfers.run_operation(queued["id"])
        self.assertEqual(apply.call_count, 1)
        self.assertEqual(active_operation()["operation_id"], queued["id"])
        self.assert_source_retained()
        with patch.object(migration_engine, "apply_candidate") as replay:
            with self.assertRaisesMessage(TransferError, "never automatically replayed"):
                upgrades.recover(queued["id"], self.actor, "retry")
        replay.assert_not_called()
        stopped = upgrades.recover(queued["id"], self.actor, "abandon")
        self.assertEqual(stopped["status"], "failed")
        self.assertIsNone(active_operation())
        for action in ("retry", "abandon"):
            with self.subTest(action=action), self.assertRaisesMessage(TransferError, "still owns maintenance"):
                upgrades.recover(queued["id"], self.actor, action)
        self.assertTrue((store.operation_dir(queued["id"]) / "restore-target.json").is_file())
        self.assertTrue((store.operation_dir(queued["id"]) / "storage-pin.json").is_file())
        self.assertTrue(store.package_path(backup["id"]).is_file())
        self.assert_source_retained()
        with connection.cursor() as cursor:
            cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname=%s)", [target])
            self.assertTrue(cursor.fetchone()[0])

    def test_restore_interruption_exposes_safe_retry_then_completes(self):
        backup = self.legacy_backup()
        queued, _target = self.start_upgrade(backup)
        with patch.object(postgres, "restore", side_effect=RuntimeError("interrupted restore")):
            with self.assertRaises(TransferError):
                transfers.run_operation(queued["id"])
        operation = upgrades.get_operation(queued["id"], self.actor)
        self.assertTrue(operation["can_retry"])
        self.assertTrue(operation["can_abandon"])
        self.assertFalse(operation.get("migration_started"))
        with patch.object(upgrades.transfers, "_launch"):
            upgrades.recover(queued["id"], self.actor, "retry")
        self.assertEqual(transfers.run_operation(queued["id"])["status"], "completed")
        self.assert_source_retained()

    def test_changed_installed_graph_invalidates_an_existing_upgrade_review(self):
        backup = self.legacy_backup()
        review = upgrades.preview(backup["id"], self.actor)
        original = migration_engine.migration_status
        def changed(database):
            value = original(database)
            value["plan_hash"] = "f" * 64
            return value
        with patch.object(migration_engine, "migration_status", side_effect=changed):
            with self.assertRaisesMessage(TransferError, "review changed"):
                upgrades.start(backup["id"], self.actor, review["review_hash"], self.generation, review["revision"])
        self.assertIsNone(active_operation())
        self.assert_source_retained()

    def test_changed_retained_file_invalidates_backup_and_upgrade_review(self):
        backup = self.legacy_backup()
        review = upgrades.preview(backup["id"], self.actor)
        self.report_path.write_bytes(b"changed by an external writer")
        with self.assertRaisesMessage(TransferError, "review changed"):
            upgrades.start(backup["id"], self.actor, review["review_hash"], self.generation, review["revision"])
        self.assertIsNone(active_operation())
        self.assertEqual(selection.current_database(), self.source)
        self.assertNotIn("django_migrations", connection.introspection.table_names())
        self.assertTrue(read_status()["enabled"])
