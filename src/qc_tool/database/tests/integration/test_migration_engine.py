"""Native graph adoption changes only an explicitly owned disposable copy."""

from contextlib import contextmanager
from copy import deepcopy
from io import StringIO
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from django.apps import apps
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.db.backends.sqlite3.base import DatabaseWrapper
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from qc_tool.database.deployment import SchemaInitializer
from qc_tool.database.migration_engine import (
    adopt_candidate_baseline, apply_candidate, inspect_source, migration_status,
)
from qc_tool.database.policy import MANAGED_APPS


@contextmanager
def candidate(*, legacy=False, postgresql=False):
    operation_id = str(uuid4())
    alias = "migration_probe_" + uuid4().hex
    settings = deepcopy(connections["default"].settings_dict)
    with TemporaryDirectory(prefix="qc-migration-candidate-") as temporary:
        if postgresql:
            if not str(connections["default"].settings_dict["NAME"]).startswith("test_"):
                raise AssertionError("PostgreSQL migration candidates require Django's disposable test database.")
            settings.update(ENGINE="django.db.backends.postgresql", NAME="qc_restore_" + operation_id.replace("-", ""))
            with connections["default"].cursor() as cursor:
                cursor.execute("CREATE DATABASE %s" % connections["default"].ops.quote_name(settings["NAME"]))
        else:
            settings.update(ENGINE="django.db.backends.sqlite3", OPTIONS={}, HOST="", PORT="", USER="", PASSWORD="",
                            NAME=str(Path(temporary) / ("qc_restore_" + operation_id.replace("-", "") + ".sqlite3")))
        connections.databases[alias] = settings
        probe = connections[alias] if postgresql else DatabaseWrapper(settings, alias=alias)
        connections[alias] = probe
        try:
            if legacy:
                with override_settings(MIGRATION_MODULES=dict.fromkeys(MANAGED_APPS)):
                    call_command("migrate", database=alias, run_syncdb=True, interactive=False, stdout=StringIO())
            else:
                SchemaInitializer(probe).apply(stdout=StringIO(), lock_timeout_ms=5000, statement_timeout_ms=300000)
            yield probe, operation_id
        finally:
            probe.close()
            del connections[alias]
            connections.databases.pop(alias, None)
            if postgresql:
                with connections["default"].cursor() as cursor:
                    cursor.execute("DROP DATABASE %s" % connections["default"].ops.quote_name(settings["NAME"]))


def approval(probe, operation_id):
    report = migration_status(probe)
    return {"operation_id": operation_id, "expected_plan_hash": report["plan_hash"],
            "expected_source_fingerprint": report["source_fingerprint"]}


@contextmanager
def installed_history(files):
    """Install only temporary graph fixtures; released files stay untouched."""
    with TemporaryDirectory(prefix="qc-invalid-history-") as temporary:
        package = Path(temporary) / ("probe_invalid_history_" + uuid4().hex)
        package.mkdir()
        (package / "__init__.py").touch()
        initial = Path(__file__).resolve().parents[3] / "frontend/dashboard/migrations/0001_initial.py"
        shutil.copyfile(initial, package / "0001_initial.py")
        for name, dependencies in files.items():
            (package / (name + ".py")).write_text(dependencies if isinstance(dependencies, str) else
                "from django.db import migrations\n"
                "class Migration(migrations.Migration):\n"
                f"    dependencies = {dependencies!r}\n"
                "    operations = []\n"
            )
        sys.path.insert(0, temporary)
        try:
            with override_settings(MIGRATION_MODULES={"dashboard": package.name}):
                yield
        finally:
            sys.path.remove(temporary)


class NativeMigrationEngineTests(TestCase):
    databases = {"default"}

    def test_legacy_postgres_recognizes_only_supported_implicit_join_id_widths(self):
        if connections["default"].vendor != "postgresql":
            self.skipTest("PostgreSQL physical integer widths are backend-specific.")
        from django.db import transaction

        joins = ("auth_group_permissions", "auth_user_groups", "auth_user_user_permissions")
        with candidate(legacy=True, postgresql=True) as (probe, _operation_id):
            for width in ("integer", "bigint"):
                with self.subTest(width=width):
                    with probe.cursor() as cursor:
                        for table in joins:
                            cursor.execute(f'ALTER TABLE "{table}" ALTER COLUMN id TYPE {width}')
                            cursor.execute(f'ALTER SEQUENCE "{table}_id_seq" AS {width}')
                    with CaptureQueriesContext(probe) as queries:
                        report = inspect_source(probe)
                    self.assertEqual(report["state"], "ready", report["problems"])
                    self.assertNotIn("django_migrations", probe.introspection.table_names())
                    self.assertFalse(any(query["sql"].lstrip().upper().startswith(
                        ("CREATE ", "ALTER ", "DROP ", "INSERT ", "UPDATE ", "DELETE ")) for query in queries))
            for table, width in ((joins[0], "smallint"), ("catalog_product", "integer")):
                with self.subTest(table=table, unsupported_width=width), transaction.atomic(using=probe.alias):
                    with probe.cursor() as cursor:
                        cursor.execute(f'ALTER TABLE "{table}" ALTER COLUMN id TYPE {width}')
                    report = inspect_source(probe)
                    self.assertEqual(report["state"], "incompatible")
                    self.assertIn(f"column type differs in {table}.id", " ".join(report["problems"]))
                    transaction.set_rollback(True, using=probe.alias)

    def test_unrenderable_recorded_historical_models_are_a_read_only_blocker(self):
        migration = (
            "from django.db import migrations\n"
            "class Migration(migrations.Migration):\n"
            "    dependencies = [('dashboard', '0001_initial')]\n"
            "    operations = [migrations.CreateModel('InvalidHistoricalBase', fields=[], bases=('foreign.MissingModel',))]\n"
        )
        with candidate() as (probe, _operation_id), installed_history({"0002_invalid_bases": migration}):
            with probe.cursor() as cursor:
                cursor.execute("INSERT INTO django_migrations(app,name,applied) VALUES ('dashboard','0002_invalid_bases',CURRENT_TIMESTAMP)")
            with CaptureQueriesContext(probe) as queries:
                report = migration_status(probe)
            self.assertEqual(report["state"], "incompatible")
            self.assertIn("InvalidBasesError", " ".join(report["problems"]))
            self.assertFalse(any(query["sql"].lstrip().upper().startswith(
                ("CREATE ", "ALTER ", "DROP ", "INSERT ", "UPDATE ", "DELETE ")) for query in queries))

    def test_complete_history_does_not_hide_unmigrated_current_model_fields(self):
        from django.db import models

        Product = apps.get_model("dashboard", "Product")
        with candidate() as (probe, operation_id):
            arguments = approval(probe, operation_id)
            field = models.CharField(max_length=32)
            Product.add_to_class("unmigrated_probe", field)
            try:
                with CaptureQueriesContext(probe) as queries:
                    report = migration_status(probe)
                    self.assertEqual(report["state"], "incompatible")
                    self.assertIn("columns differ in catalog_product", " ".join(report["problems"]))
                    with self.assertRaises(CommandError):
                        apply_candidate(probe, **arguments)
                self.assertFalse(any(query["sql"].lstrip().upper().startswith(
                    ("CREATE ", "ALTER ", "DROP ", "INSERT ", "UPDATE ", "DELETE ")) for query in queries))
            finally:
                Product._meta.local_fields.remove(field)
                delattr(Product, field.attname)
                Product._meta._expire_cache()

    def test_native_declared_database_defaults_and_generated_columns_are_verified(self):
        from django.db import models

        Product = apps.get_model("dashboard", "Product")
        migration = (
            "from django.db import migrations, models\n"
            "class Migration(migrations.Migration):\n"
            "    dependencies = [('dashboard', '0001_initial')]\n"
            "    operations = [\n"
            "        migrations.AddField('product', 'database_default_probe', models.CharField(max_length=32, db_default='retained')),\n"
            "        migrations.AddField('product', 'generated_probe', models.GeneratedField(expression=models.F('id') * 2, output_field=models.BigIntegerField(), db_persist=True)),\n"
            "    ]\n"
        )
        for drift in ("default", "generated"):
            with self.subTest(drift=drift), candidate(postgresql=connections["default"].vendor == "postgresql") as (probe, operation_id):
                default = models.CharField(max_length=32, db_default="retained")
                generated = models.GeneratedField(expression=models.F("id") * 2, output_field=models.BigIntegerField(), db_persist=True)
                Product.add_to_class("database_default_probe", default)
                Product.add_to_class("generated_probe", generated)
                try:
                    with installed_history({"0002_declared_expressions": migration}):
                        self.assertEqual(migration_status(probe)["state"], "pending")
                        result = apply_candidate(probe, **approval(probe, operation_id))
                        self.assertEqual(result["state"], "ready", result["problems"])
                        product = Product.objects.using(probe.alias).create(ident="native-defaults", name="Original data")
                        product.refresh_from_db(using=probe.alias)
                        self.assertEqual(product.database_default_probe, "retained")
                        self.assertEqual(product.generated_probe, product.pk * 2)
                        if drift == "default":
                            altered = models.CharField(max_length=32, db_default="unexpected")
                            altered.set_attributes_from_name(default.name)
                            altered.model = Product
                            with probe.schema_editor() as editor:
                                editor.alter_field(Product, default, altered)
                        else:
                            # SQLite cannot add a STORED generated column to a
                            # populated table. Retain the separate positive-row
                            # proof above, then alter this disposable empty table.
                            Product.objects.using(probe.alias).all().delete()
                            altered = models.GeneratedField(expression=models.F("id") * 3, output_field=models.BigIntegerField(), db_persist=True)
                            altered.set_attributes_from_name(generated.name)
                            altered.model = Product
                            # GeneratedField normally receives its expression
                            # resolver during contribute_to_class. Keep the
                            # installed model declaration unchanged in this
                            # deliberately drifted physical-column fixture.
                            from django.db.models.sql import Query
                            altered._query = Query(model=Product, alias_cols=False)
                            with probe.schema_editor() as editor:
                                editor.remove_field(Product, generated)
                                editor.add_field(Product, altered)
                        report = migration_status(probe)
                        self.assertEqual(report["state"], "incompatible")
                        self.assertIn("database default expression" if drift == "default" else "generated expression", " ".join(report["problems"]))
                finally:
                    for field in (default, generated):
                        Product._meta.local_fields.remove(field)
                        delattr(Product, field.attname)
                    Product._meta._expire_cache()

    def test_invalid_or_conflicting_installed_graph_is_a_read_only_blocker(self):
        graphs = (
            ({"0002_missing_parent": [("dashboard", "0099_not_installed")]}, "NodeNotFoundError"),
            ({"0002_invalid_python": "from django.db import migrations\nclass Migration(\n"}, "SyntaxError"),
            ({"0002_missing_helper": "import qc_tool_migration_helper_that_is_not_installed\n"}, "ModuleNotFoundError"),
            ({"0002_cycle": [("dashboard", "0003_cycle")],
              "0003_cycle": [("dashboard", "0002_cycle")]}, "CircularDependencyError"),
            ({"0002_branch_a": [("dashboard", "0001_initial")],
              "0002_branch_b": [("dashboard", "0001_initial")]}, "conflicting Django migration leaves"),
        )
        for legacy in (False, True):
            for files, message in graphs:
                with self.subTest(legacy=legacy, graph=message), candidate(legacy=legacy) as (probe, operation_id):
                    arguments = approval(probe, operation_id)
                    with installed_history(files), CaptureQueriesContext(probe) as queries:
                        report = migration_status(probe)
                        self.assertEqual(report["state"], "incompatible")
                        self.assertIn(message, " ".join(report["problems"]))
                        with self.assertRaises(CommandError):
                            apply_candidate(probe, **arguments)
                    self.assertFalse(any(query["sql"].lstrip().upper().startswith(
                        ("CREATE ", "ALTER ", "DROP ", "INSERT ", "UPDATE ", "DELETE ")) for query in queries))
                    self.assertEqual("django_migrations" in probe.introspection.table_names(), not legacy)

    def test_managed_graph_is_current_and_repeat_candidate_apply_is_read_only(self):
        with candidate() as (probe, operation_id):
            report = migration_status(probe)
            self.assertEqual(report["state"], "ready", report["problems"])
            self.assertFalse(report["pending"])
            self.assertTrue(all(len(item["sha256"]) == 64 for item in report["graph"]))
            with patch("qc_tool.database.migration_engine.candidates.call_command", side_effect=AssertionError("Repeated migrate")):
                with CaptureQueriesContext(probe) as queries:
                    apply_candidate(probe, **approval(probe, operation_id))
            writes = [query["sql"] for query in queries if query["sql"].lstrip().upper().startswith(
                ("CREATE ", "ALTER ", "DROP ", "INSERT ", "UPDATE ", "DELETE "))]
            self.assertEqual(writes, [])

    def test_history_free_source_inspection_is_read_only_and_adoption_preserves_rows(self):
        with candidate(legacy=True) as (probe, operation_id):
            Product = apps.get_model("dashboard", "Product")
            Product.objects.using(probe.alias).create(ident="retained-product", name="Preserve this catalog")
            before = list(Product.objects.using(probe.alias).values())
            with CaptureQueriesContext(probe) as queries:
                source = inspect_source(probe)
                report = migration_status(probe)
            self.assertEqual(source["state"], "ready", source["problems"])
            self.assertEqual(report["state"], "legacy", report["problems"])
            self.assertNotIn("django_migrations", probe.introspection.table_names())
            self.assertFalse(any(query["sql"].lstrip().upper().startswith(("CREATE ", "INSERT ", "UPDATE ", "DELETE ")) for query in queries))
            result = apply_candidate(probe, **approval(probe, operation_id))
            self.assertEqual(result["state"], "ready", result["problems"])
            self.assertEqual(before, list(Product.objects.using(probe.alias).values()))
            self.assertIn("django_migrations", probe.introspection.table_names())
            self.assertTrue({"auth", "admin", "contenttypes", "sessions", "accounts", "dashboard", "qc_database"}.issubset(
                {item["app"] for item in result["applied"]}))

    def test_adoption_refuses_serving_alias_wrong_operation_and_stale_review(self):
        with candidate(legacy=True) as (probe, operation_id):
            arguments = approval(probe, operation_id)
            for changes in ({"operation_id": str(uuid4())}, {"expected_plan_hash": "0" * 64},
                            {"expected_source_fingerprint": "0" * 64}):
                with self.subTest(changes=changes), self.assertRaises(CommandError):
                    adopt_candidate_baseline(probe, **{**arguments, **changes})
                self.assertNotIn("django_migrations", probe.introspection.table_names())
            with patch.object(probe, "alias", "default"), self.assertRaisesRegex(CommandError, "separately registered"):
                adopt_candidate_baseline(probe, **arguments)
            self.assertNotIn("django_migrations", probe.introspection.table_names())

    def test_manual_extra_table_index_trigger_and_check_are_not_adopted(self):
        for ddl in (
            "CREATE TABLE foreign_data (id integer)",
            "CREATE INDEX unreviewed_product_index ON catalog_product(name)",
            "CREATE TRIGGER unreviewed_product_trigger AFTER UPDATE ON catalog_product BEGIN SELECT 1; END",
        ):
            with self.subTest(ddl=ddl), candidate(legacy=True) as (probe, operation_id):
                arguments = approval(probe, operation_id)
                with probe.cursor() as cursor:
                    cursor.execute(ddl)
                self.assertEqual(migration_status(probe)["state"], "incompatible")
                with self.assertRaises(CommandError):
                    apply_candidate(probe, **arguments)
                self.assertNotIn("django_migrations", probe.introspection.table_names())

    def test_unknown_and_inconsistent_native_history_are_refused(self):
        with candidate() as (probe, operation_id):
            with probe.cursor() as cursor:
                cursor.execute("INSERT INTO django_migrations(app,name,applied) VALUES ('foreign','9999_unknown',CURRENT_TIMESTAMP)")
            report = migration_status(probe)
            self.assertEqual(report["state"], "incompatible")
            self.assertIn("unknown applied", " ".join(report["problems"]))
            with probe.cursor() as cursor:
                cursor.execute("DELETE FROM django_migrations WHERE app='foreign'")
                cursor.execute("DELETE FROM django_migrations WHERE app='auth' AND name='0011_update_proxy_permissions'")
            report = migration_status(probe)
            self.assertEqual(report["state"], "incompatible")
            self.assertIn("before its dependency", " ".join(report["problems"]))

    def test_duplicate_native_history_is_not_hidden_by_djangos_applied_dict(self):
        with candidate() as (probe, _operation_id):
            with probe.cursor() as cursor:
                cursor.execute("INSERT INTO django_migrations(app,name,applied) VALUES ('auth','0012_alter_user_first_name_max_length',CURRENT_TIMESTAMP)")
            report = migration_status(probe)
            self.assertEqual(report["state"], "incompatible")
            self.assertIn("duplicate applied", " ".join(report["problems"]))

    def test_extra_same_table_check_cannot_be_adopted(self):
        with candidate(legacy=True) as (probe, operation_id):
            arguments = approval(probe, operation_id)
            with probe.cursor() as cursor:
                cursor.execute("SELECT sql FROM sqlite_master WHERE name='catalog_product'")
                original = cursor.fetchone()[0]
                cursor.execute("DROP TABLE catalog_product")
                cursor.execute(original.rsplit(")", 1)[0] + ", CHECK (TRUE))")
            report = migration_status(probe)
            self.assertEqual(report["state"], "incompatible")
            self.assertIn("unexpected check expression", " ".join(report["problems"]))
            with self.assertRaises(CommandError):
                apply_candidate(probe, **arguments)
            self.assertNotIn("django_migrations", probe.introspection.table_names())

    def test_collation_database_default_and_additional_constraint_drift_are_refused(self):
        changes = (
            ("collation", lambda ddl: ddl.replace('"name" varchar(200) NOT NULL', '"name" varchar(200) COLLATE NOCASE NOT NULL')),
            ("database default", lambda ddl: ddl.replace('"name" varchar(200) NOT NULL', '\"name\" varchar(200) NOT NULL DEFAULT \'unexpected\'')),
            ("unique/primary", lambda ddl: ddl.rsplit(")", 1)[0] + ', UNIQUE ("name"))'),
            ("check expression", lambda ddl: ddl.rsplit(")", 1)[0] + ', CHECK (NOT ("ident" = \'\')))'),
        )
        for message, change in changes:
            with self.subTest(message=message), candidate(legacy=True) as (probe, operation_id):
                with probe.cursor() as cursor:
                    cursor.execute("SELECT sql FROM sqlite_master WHERE name='catalog_product'")
                    original = cursor.fetchone()[0]
                    changed = change(original)
                    self.assertNotEqual(original, changed)
                    cursor.execute("DROP TABLE catalog_product")
                    cursor.execute(changed)
                report = migration_status(probe)
                self.assertEqual(report["state"], "incompatible")
                self.assertIn(message, " ".join(report["problems"]))
                self.assertNotIn("django_migrations", probe.introspection.table_names())

    def test_baseline_adoption_never_runs_auth_bootstrap(self):
        with candidate(legacy=True) as (probe, operation_id):
            from django.contrib.auth.models import Group
            group = Group.objects.using(probe.alias).get(name="admin")
            group.permissions.clear()
            with patch("qc_tool.database.migration_engine.candidates.call_command", side_effect=AssertionError("Bootstrap would change grants")):
                apply_candidate(probe, **approval(probe, operation_id))
            self.assertFalse(group.permissions.using(probe.alias).exists())
            self.assertEqual(migration_status(probe)["state"], "ready")
            self.assertIn("catalog_product", probe.introspection.table_names())

    def test_failed_adoption_rolls_back_the_complete_history(self):
        from django.db.migrations.executor import MigrationExecutor
        native = MigrationExecutor.migrate

        def fail(executor, *args, **kwargs):
            native(executor, *args, **kwargs)
            raise CommandError("Synthetic adoption failure")

        with candidate(legacy=True) as (probe, operation_id):
            with patch.object(MigrationExecutor, "migrate", fail):
                with self.assertRaisesRegex(CommandError, "Synthetic adoption failure"):
                    apply_candidate(probe, **approval(probe, operation_id))
            self.assertEqual(migration_status(probe)["state"], "legacy")
            self.assertNotIn("django_migrations", probe.introspection.table_names())


    def test_future_forward_django_data_migration_runs_on_candidate(self):
        with candidate() as (probe, operation_id), TemporaryDirectory(prefix="qc-forward-history-") as temporary:
            Product = apps.get_model("dashboard", "Product")
            Product.objects.using(probe.alias).create(ident="migration-source", name="Before forward migration")
            package = Path(temporary) / ("probe_history_" + uuid4().hex)
            package.mkdir()
            (package / "__init__.py").touch()
            initial = Path(__file__).resolve().parents[3] / "frontend/dashboard/migrations/0001_initial.py"
            shutil.copyfile(initial, package / "0001_initial.py")
            (package / "0002_forward_probe.py").write_text(
                "from django.db import migrations\n"
                "def forwards(apps, schema_editor):\n"
                "    apps.get_model('dashboard', 'Product').objects.using(schema_editor.connection.alias).filter(ident='migration-source').update(name='After forward migration')\n"
                "class Migration(migrations.Migration):\n"
                "    dependencies = [('dashboard', '0001_initial')]\n"
                "    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]\n"
            )
            sys.path.insert(0, temporary)
            try:
                with override_settings(MIGRATION_MODULES={"dashboard": package.name}):
                    report = migration_status(probe)
                    self.assertEqual(report["state"], "pending", report["problems"])
                    self.assertEqual(report["pending"][0]["name"], "0002_forward_probe")
                    result = apply_candidate(probe, **approval(probe, operation_id))
                    self.assertEqual(result["state"], "ready", result["problems"])
                    self.assertEqual(Product.objects.using(probe.alias).get(ident="migration-source").name, "After forward migration")
            finally:
                sys.path.remove(temporary)

    def test_future_schema_migration_and_atomic_failure_preserve_existing_rows(self):
        """Exercise actual DDL through Django, including rollback of failed DDL."""
        from django.db import models

        Product = apps.get_model("dashboard", "Product")
        for fail in (False, True):
            with self.subTest(fail=fail), candidate() as (probe, operation_id), TemporaryDirectory(prefix="qc-schema-forward-") as temporary:
                Product.objects.using(probe.alias).create(ident="schema-source", name="Retained before schema upgrade")
                package = Path(temporary) / ("probe_schema_history_" + uuid4().hex)
                package.mkdir()
                (package / "__init__.py").touch()
                initial = Path(__file__).resolve().parents[3] / "frontend/dashboard/migrations/0001_initial.py"
                shutil.copyfile(initial, package / "0001_initial.py")
                (package / "0002_schema_probe.py").write_text(
                    "from django.db import migrations, models\n"
                    "def abort(apps, schema_editor):\n"
                    "    raise RuntimeError('Synthetic atomic migration failure')\n"
                    "class Migration(migrations.Migration):\n"
                    "    dependencies = [('dashboard', '0001_initial')]\n"
                    "    operations = [migrations.AddField('product', 'schema_upgrade_probe', models.CharField(max_length=32, default='retained'))]"
                    + (" + [migrations.RunPython(abort, migrations.RunPython.noop)]\n" if fail else "\n")
                )
                field = models.CharField(max_length=32, default="retained")
                Product.add_to_class("schema_upgrade_probe", field)
                sys.path.insert(0, temporary)
                try:
                    with override_settings(MIGRATION_MODULES={"dashboard": package.name}):
                        report = migration_status(probe)
                        self.assertEqual(report["state"], "pending", report["problems"])
                        arguments = approval(probe, operation_id)
                        if fail:
                            with self.assertRaisesRegex(RuntimeError, "Synthetic atomic migration failure"):
                                apply_candidate(probe, **arguments)
                            self.assertEqual(migration_status(probe)["state"], "pending")
                        else:
                            self.assertEqual(apply_candidate(probe, **arguments)["state"], "ready")
                            self.assertEqual(Product.objects.using(probe.alias).get(ident="schema-source").schema_upgrade_probe, "retained")
                        with probe.cursor() as cursor:
                            cursor.execute("SELECT ident,name FROM catalog_product WHERE ident='schema-source'")
                            self.assertEqual(cursor.fetchone(), ("schema-source", "Retained before schema upgrade"))
                            columns = {column.name for column in probe.introspection.get_table_description(cursor, "catalog_product")}
                        self.assertEqual("schema_upgrade_probe" in columns, not fail)
                finally:
                    sys.path.remove(temporary)
                    Product._meta.local_fields.remove(field)
                    delattr(Product, field.attname)
                    Product._meta._expire_cache()
