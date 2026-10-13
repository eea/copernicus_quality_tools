"""Empty initialization, occupied-schema refusal and PostgreSQL serialization."""

from contextlib import contextmanager
from copy import deepcopy
from io import StringIO
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, connections
from django.db.backends.sqlite3.base import DatabaseWrapper
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from qc_tool.database.deployment import SCHEMA_LOCK, SchemaInitializer, schema_lock


@contextmanager
def fresh_sqlite():
    """Every destructive guard probe owns a separate disposable target."""
    original = connections["default"]
    settings = deepcopy(original.settings_dict)
    settings.update(ENGINE="django.db.backends.sqlite3", OPTIONS={}, HOST="", PORT="", USER="", PASSWORD="")
    with TemporaryDirectory(prefix="qc-empty-schema-test-") as temporary:
        settings["NAME"] = str(Path(temporary) / "probe.sqlite3")
        probe = DatabaseWrapper(settings, alias="default")
        ContentType.objects.clear_cache()
        connections["default"] = probe
        try:
            yield probe
        finally:
            probe.close()
            connections["default"] = original
            ContentType.objects.clear_cache()


def initialize():
    call_command("database", "apply", stdout=StringIO(), skip_checks=True)


@override_settings(IS_SECURE_ENVIRONMENT=True)
class DatabaseInitializationTests(SimpleTestCase):
    databases = {"default"}

    def test_timeouts_must_be_positive_and_bounded(self):
        for option in ("lock_timeout_ms", "statement_timeout_ms"):
            for value in (0, -1, 2147483648):
                with self.subTest(option=option, value=value), self.assertRaises(CommandError):
                    call_command("database", "apply", skip_checks=True, **{option: value})

    def test_empty_production_target_creates_models_and_roles_without_data_or_history(self):
        with fresh_sqlite() as probe:
            call_command("database", "plan", stdout=StringIO(), skip_checks=True)
            self.assertFalse(Path(probe.settings_dict["NAME"]).exists())
            initialize()
            self.assertEqual(SchemaInitializer(probe).check()["state"], "ready")
            self.assertNotIn("django_migrations", probe.introspection.table_names())
            self.assertFalse(get_user_model().objects.exists())
            self.assertFalse(apps.get_model("dashboard", "Product").objects.exists())
            self.assertTrue(Permission.objects.exists())
            self.assertTrue(Group.objects.filter(name="admin").exists())
            with probe.cursor() as cursor:
                cursor.execute("SELECT sql FROM sqlite_master WHERE name='execution_delivery_subname_idx'")
                definition = cursor.fetchone()[0]
            self.assertIn("LOWER", definition.upper())
            self.assertIn("IS NOT NULL", definition.upper())

    def test_matching_populated_target_is_read_only_and_never_bootstraps(self):
        with fresh_sqlite() as probe:
            initialize()
            user = get_user_model().objects.create_user("retained-user", password="retained-password")
            get_user_model().objects.filter(pk=user.pk).update(is_staff=True)
            product = apps.get_model("dashboard", "Product").objects.create(ident="retained", name="Retained")
            grants = apps.get_model("accounts", "UserProductGrant")
            grants.objects.create(user=user, product_ident=product.ident)
            Group.objects.get(name="admin").permissions.clear()
            before = (list(get_user_model().objects.values()), list(Group.permissions.through.objects.values()),
                      list(grants.objects.values()))
            with patch("qc_tool.database.deployment.call_command", side_effect=AssertionError("bootstrap invoked")):
                with CaptureQueriesContext(probe) as queries:
                    for action in ("plan", "check", "apply", "check"):
                        call_command("database", action, stdout=StringIO(), skip_checks=True)
            after = (list(get_user_model().objects.values()), list(Group.permissions.through.objects.values()),
                     list(grants.objects.values()))
            self.assertEqual(before, after)
            mutating = re.compile(r"^\s*(?:INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|REPLACE)\b", re.I)
            self.assertFalse(any(mutating.match(query["sql"]) for query in queries.captured_queries))

    def test_partial_foreign_tables_and_views_are_refused_before_initialization(self):
        for ddl in ("CREATE TABLE retained (id integer, note text)",
                    "CREATE VIEW retained AS SELECT 1 AS id",
                    "CREATE TABLE catalog_product (id integer PRIMARY KEY)"):
            with self.subTest(ddl=ddl), fresh_sqlite() as probe:
                with probe.cursor() as cursor:
                    cursor.execute(ddl)
                    cursor.execute("SELECT sql FROM sqlite_master WHERE name='retained' OR name='catalog_product'")
                    before = cursor.fetchall()
                with patch("qc_tool.database.deployment.call_command") as native:
                    for action in ("plan", "check", "apply"):
                        with self.assertRaisesMessage(CommandError, "not ready"):
                            call_command("database", action, stdout=StringIO(), skip_checks=True)
                    native.assert_not_called()
                with probe.cursor() as cursor:
                    cursor.execute("SELECT sql FROM sqlite_master WHERE name='retained' OR name='catalog_product'")
                    self.assertEqual(before, cursor.fetchall())

    def test_missing_or_wrong_submission_name_index_is_not_repaired(self):
        for replacement in (None,
                            'CREATE INDEX execution_delivery_subname_idx ON execution_delivery (UPPER(filename)) WHERE date_submitted IS NOT NULL',
                            'CREATE INDEX execution_delivery_subname_idx ON execution_delivery (LOWER(filename)) WHERE date_submitted IS NULL'):
            with self.subTest(replacement=replacement), fresh_sqlite() as probe:
                initialize()
                with probe.cursor() as cursor:
                    cursor.execute("DROP INDEX execution_delivery_subname_idx")
                    if replacement:
                        cursor.execute(replacement)
                with patch("qc_tool.database.deployment.call_command") as native:
                    with self.assertRaisesMessage(CommandError, "index"):
                        call_command("database", "apply", stdout=StringIO(), skip_checks=True)
                    native.assert_not_called()
                with probe.cursor() as cursor:
                    cursor.execute("SELECT sql FROM sqlite_master WHERE name='execution_delivery_subname_idx'")
                    row = cursor.fetchone()
                self.assertEqual(row[0] if row else None, replacement)

    def test_column_type_nullability_and_pk_generation_drift_are_refused(self):
        changes = (
            ('"ident" varchar(64)', '"ident" text', "column type differs"),
            ('"ident" varchar(64) NOT NULL', '"ident" varchar(64)', "column nullability differs"),
            ('AUTOINCREMENT', '', "automatic primary key generation differs"),
        )
        for old, new, expected in changes:
            with self.subTest(expected=expected), fresh_sqlite() as probe:
                initialize()
                with probe.cursor() as cursor:
                    cursor.execute("SELECT sql FROM sqlite_master WHERE name='catalog_product'")
                    ddl = cursor.fetchone()[0]
                    self.assertIn(old, ddl)
                    cursor.execute("DROP TABLE catalog_product")
                    cursor.execute(ddl.replace(old, new))
                with patch("qc_tool.database.deployment.call_command") as native:
                    with self.assertRaisesMessage(CommandError, expected):
                        call_command("database", "apply", stdout=StringIO(), skip_checks=True)
                    native.assert_not_called()

    def test_same_named_check_replaced_by_true_is_refused(self):
        with fresh_sqlite() as probe:
            initialize()
            with probe.cursor() as cursor:
                cursor.execute("SELECT sql FROM sqlite_master WHERE name='catalog_product'")
                ddl = cursor.fetchone()[0]
                changed, count = re.subn(
                    r'CONSTRAINT "catalog_product_ident_present" CHECK \(NOT \("ident" = \'\'\)\)',
                    'CONSTRAINT "catalog_product_ident_present" CHECK (TRUE)', ddl,
                )
                self.assertEqual(count, 1)
                cursor.execute("DROP TABLE catalog_product")
                cursor.execute(changed)
            with patch("qc_tool.database.deployment.call_command") as native:
                with self.assertRaisesMessage(CommandError, "catalog_product_ident_present"):
                    call_command("database", "apply", stdout=StringIO(), skip_checks=True)
                native.assert_not_called()
            with probe.cursor() as cursor:
                cursor.execute("SELECT sql FROM sqlite_master WHERE name='catalog_product'")
                self.assertEqual(cursor.fetchone()[0], changed)
                cursor.execute("SELECT COUNT(*) FROM catalog_product")
                self.assertEqual(cursor.fetchone()[0], 0)

    def test_partial_index_cannot_replace_unconditional_username_uniqueness(self):
        with fresh_sqlite() as probe:
            initialize()
            with probe.cursor() as cursor:
                cursor.execute("SELECT sql FROM sqlite_master WHERE name='auth_user'")
                ddl = cursor.fetchone()[0]
                original = '"username" varchar(150) NOT NULL UNIQUE'
                self.assertIn(original, ddl)
                cursor.execute("DROP TABLE auth_user")
                cursor.execute(ddl.replace(original, '"username" varchar(150) NOT NULL'))
                cursor.execute("CREATE UNIQUE INDEX probe_partial_username ON auth_user (username) WHERE is_active")
            with patch("qc_tool.database.deployment.call_command") as native:
                with self.assertRaisesMessage(CommandError, "unique key differs in auth_user (username)"):
                    call_command("database", "apply", stdout=StringIO(), skip_checks=True)
                native.assert_not_called()


class DatabaseDeploymentTests(TransactionTestCase):
    def test_application_tables_have_explicit_business_domain_names(self):
        tables = set(connection.introspection.table_names())
        prefixes = ("account_", "catalog_", "execution_", "publication_", "storage_")
        for model in apps.get_models():
            if model._meta.app_label not in {"accounts", "dashboard"} or not model._meta.managed:
                continue
            with self.subTest(model=model._meta.label):
                self.assertIn("db_table", model._meta.original_attrs)
                self.assertTrue(model._meta.db_table.startswith(prefixes))
                self.assertIn(model._meta.db_table, tables)
        self.assertFalse(any(name.startswith("dashboard_") for name in tables))
        self.assertNotIn("django_migrations", tables)

    def test_whole_application_readiness_and_repeated_application(self):
        for action in ("plan", "check", "apply", "check"):
            call_command("database", action, stdout=StringIO())

    def test_postgres_other_schema_objects_prevent_initialization(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL namespaces are backend-specific.")
        with connection.cursor() as cursor:
            cursor.execute("CREATE SCHEMA qc_schema_guard_probe")
            cursor.execute("CREATE TABLE qc_schema_guard_probe.retained (id integer)")
        try:
            with patch("qc_tool.database.deployment.call_command") as native:
                with self.assertRaisesMessage(CommandError, "qc_schema_guard_probe.retained"):
                    call_command("database", "apply", stdout=StringIO())
                native.assert_not_called()
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DROP SCHEMA qc_schema_guard_probe CASCADE")

    def test_postgres_identity_always_changes_explicit_id_contract(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL identity modes are backend-specific.")
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE catalog_product ALTER COLUMN id SET GENERATED ALWAYS")
        try:
            with self.assertRaisesMessage(CommandError, "automatic primary key generation differs"):
                call_command("database", "check", stdout=StringIO())
        finally:
            with connection.cursor() as cursor:
                cursor.execute("ALTER TABLE catalog_product ALTER COLUMN id SET GENERATED BY DEFAULT")

    def test_postgres_lock_excludes_other_initializers_and_restores_timeouts(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL advisory locks are backend-specific.")
        other = connection.copy(alias="schema_lock_test")
        self.addCleanup(other.close)
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('lock_timeout'), current_setting('statement_timeout')")
            previous = cursor.fetchone()
        with schema_lock(connection, lock_timeout_ms=1000, statement_timeout_ms=3000):
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_setting('lock_timeout'), current_setting('statement_timeout')")
                self.assertEqual(cursor.fetchone(), ("1s", "3s"))
            with self.assertRaisesMessage(CommandError, "Another QC Tool"):
                with schema_lock(other, lock_timeout_ms=1000, statement_timeout_ms=3000):
                    self.fail("A second initialization acquired the same lock.")
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('lock_timeout'), current_setting('statement_timeout')")
            self.assertEqual(cursor.fetchone(), previous)
        with other.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", SCHEMA_LOCK)
            self.assertTrue(cursor.fetchone()[0])
            cursor.execute("SELECT pg_advisory_unlock(%s, %s)", SCHEMA_LOCK)

    def test_postgres_lock_releases_after_failure(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL advisory locks are backend-specific.")
        with self.assertRaisesRegex(RuntimeError, "probe"):
            with schema_lock(connection, lock_timeout_ms=1000, statement_timeout_ms=3000):
                raise RuntimeError("probe")
        other = connection.copy(alias="schema_failure_test")
        self.addCleanup(other.close)
        with schema_lock(other, lock_timeout_ms=1000, statement_timeout_ms=3000):
            pass

    def test_closed_postgres_connection_does_not_mask_initialization_error(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL advisory locks are backend-specific.")
        with self.assertRaisesRegex(RuntimeError, "original initialization failure"):
            with schema_lock(connection, lock_timeout_ms=1000, statement_timeout_ms=3000):
                connection.close()
                raise RuntimeError("original initialization failure")
        other = connection.copy(alias="schema_closed_connection_test")
        self.addCleanup(other.close)
        with schema_lock(other, lock_timeout_ms=1000, statement_timeout_ms=3000):
            pass
