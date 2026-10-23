"""Native backup contracts and real restoration only on disposable databases."""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import re
import stat
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import Mock, patch
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, transaction
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.utils import timezone

from qc_tool.database.transfers import postgres
from qc_tool.database.transfers.archive import ArtifactSource, inspect_archive, write_archive
from qc_tool.database.transfers.contracts import digest
from qc_tool.database.transfers.errors import TransferError
from qc_tool.frontend.accounts.models import PersonalAccessToken
from qc_tool.frontend.dashboard.services import maintenance
from qc_tool.frontend.dashboard.services.maintenance.operations import active_operation


def metadata(data=b"PGDMPfixture"):
    source = {"oid": 123, "database": "source_database", "server_version": "14.24",
              "server_major": 14, "encoding": "UTF8", "collation": "C", "ctype": "C",
              "dump_version": "pg_dump (PostgreSQL) 14.24", "restore_version": "pg_restore (PostgreSQL) 14.24"}
    inventory = {"tables": [], "sequences": [], "large_objects": [], "total_rows": 0,
                 "schema_sha256": hashlib.sha256(b"").hexdigest()}
    created = "2026-10-21T12:00:00+00:00"
    return {"format": postgres.FORMAT, "version": 1, "created_at": created,
            "source": source, "inventory": inventory, "review_hash": digest({"source": source, "inventory": inventory}),
            "counts": {"tables": 0, "rows": 0},
            "source_details": {"app_version": "3.0.0", "postgresql_version": "14.24",
                               "source_database": source["database"], "exported_at": created},
            "dump_sha256": hashlib.sha256(data).hexdigest(), "dump_bytes": len(data)}


@override_settings(QC_TOOL_TRANSFER_MIN_FREE_BYTES=1024**2)
class NativePostgresSafetyTests(SimpleTestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory()))

    def package(self, data=b"PGDMPfixture", records=None):
        dump = self.directory / (uuid4().hex + ".dump")
        dump.write_bytes(data)
        path = self.directory / (uuid4().hex + ".zip")
        write_archive(path, {}, records or metadata(data), (ArtifactSource("database", "archive.dump", dump),))
        return inspect_archive(path)

    def test_sqlite_explains_native_support_without_falling_back_to_partial_export(self):
        with patch.object(postgres, "_params", side_effect=TransferError("Complete native database copies require PostgreSQL.")):
            status = postgres.availability()
        self.assertFalse(status["available"])
        self.assertIn("PostgreSQL", status["reason"])

    def test_tool_credentials_stay_in_private_files_and_preserve_tls(self):
        password = "private:credential\\value"
        with patch.dict(os.environ, {"PGPASSWORD": "ambient-secret", "PGDATABASE": "wrong-target"}):
            with postgres._tool_environment({"dbname": "source", "user": "operator", "host": "db.example",
                    "password": password, "sslmode": "verify-full", "sslrootcert": "/private/ca.pem"}) as environment:
                self.assertNotIn("PGPASSWORD", environment)
                self.assertNotIn("PGDATABASE", environment)
                self.assertNotIn(password, repr(environment))
                service = Path(environment["PGSERVICEFILE"])
                passfile = Path(environment["PGPASSFILE"])
                self.assertEqual(stat.S_IMODE(service.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(passfile.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(service.parent.stat().st_mode), 0o700)
                self.assertIn("sslmode=verify-full", service.read_text())
                self.assertIn("sslrootcert=/private/ca.pem", service.read_text())
                self.assertNotIn(password, service.read_text())
                self.assertIn(r"private\:credential\\value", passfile.read_text())
            self.assertFalse(service.exists())
            self.assertFalse(passfile.exists())

    def test_tool_failure_never_exposes_diagnostic_secrets(self):
        with self.assertRaises(TransferError) as raised:
            postgres._run_tool([sys.executable, "-c", "import sys;sys.stderr.write('password=hidden-token');sys.exit(1)"])
        self.assertNotIn("hidden-token", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

    def test_tool_diagnostic_volume_is_bounded(self):
        with patch.object(postgres, "_MAX_DIAGNOSTIC_BYTES", 128):
            with self.assertRaisesMessage(TransferError, "too much metadata"):
                postgres._run_tool([sys.executable, "-c", "print('x'*10000)"])

    @override_settings(QC_TOOL_POSTGRES_TOOL_TIMEOUT=1)
    def test_tool_timeout_terminates_the_process(self):
        with self.assertRaisesMessage(TransferError, "timeout"):
            postgres._run_tool([sys.executable, "-c", "import time;time.sleep(10)"])

    def test_native_inspection_lists_but_does_not_execute_sql(self):
        verified = self.package()
        with patch.object(postgres, "_toolchain", return_value={"pg_restore": "pg_restore"}), patch.object(postgres, "_run_tool", return_value=b"readable inventory") as run:
            self.assertEqual(postgres.inspect_native(verified), verified.records)
        arguments = run.call_args.args[0]
        self.assertEqual(arguments[:2], ["pg_restore", "--list"])
        self.assertFalse(any(argument.startswith("--dbname") for argument in arguments))
        self.assertEqual(list(self.directory.glob(".qc-postgres-archive-*")), [])

    def test_arbitrary_sql_cannot_disguise_itself_as_a_custom_archive(self):
        verified = self.package(b"DROP TABLE auth_user;")
        with patch.object(postgres, "_toolchain", return_value={"pg_restore": "pg_restore"}), patch.object(postgres, "_run_tool") as run:
            with self.assertRaisesMessage(TransferError, "custom archive"):
                postgres.inspect_native(verified)
        run.assert_not_called()

    def test_malformed_native_inventory_and_fingerprints_are_controlled_errors(self):
        original = metadata()
        for change in ({"version": True}, {"created_at": "yesterday"}, {"dump_sha256": "0" * 64},
                       {"counts": []}, {"review_hash": "0" * 64}, {"inventory": []}):
            with self.subTest(field=next(iter(change))):
                records = {**deepcopy(original), **change}
                with self.assertRaises(TransferError):
                    postgres._native_metadata(self.package(records=records))

    def test_restore_target_accepts_only_one_configured_database_name(self):
        for name in ("", "postgresql://server/database", "dbname=source", "source; DROP DATABASE source", "../source", "a" * 64):
            with self.subTest(name=name), override_settings(QC_TOOL_RESTORE_DATABASE=name):
                with self.assertRaises(TransferError):
                    postgres._target_name()
        with override_settings(QC_TOOL_RESTORE_DATABASE="qc_restore_2026"):
            self.assertEqual(postgres._target_name(), "qc_restore_2026")
        with override_settings(QC_TOOL_RESTORE_DATABASE="unused_configured_target"):
            self.assertEqual(postgres._target_name("server_owned_target"), "server_owned_target")

    def test_database_preparation_requires_the_serialized_execution_lease(self):
        with self.assertRaisesMessage(TransferError, "serialized administrator"):
            postgres.prepare_restore_target(object(), str(uuid4()))

    def test_generated_names_are_canonical_and_legacy_locale_is_not_guessed(self):
        operation = uuid4()
        self.assertEqual(postgres.restore_database_name(str(operation)), "qc_restore_" + operation.hex)
        with self.assertRaises(TransferError):
            postgres.restore_database_name("postgresql://untrusted/target")
        self.assertEqual(postgres._archive_locale(metadata()["source"])["locale_provider"], "libc")
        with self.assertRaisesMessage(TransferError, "locale provider"):
            postgres._archive_locale({**metadata()["source"], "server_major": 15})

    def test_target_fingerprint_binds_identity_without_password_material(self):
        source = {"oid": 1, "database": "source"}
        target = {"oid": 2, "database": "target", "server_major": 14}
        params = {"host": "db", "port": "5432", "password": "first-password"}
        original = postgres._target_fingerprint(params, source, target)
        self.assertEqual(original, postgres._target_fingerprint({**params, "password": "rotated-password"}, source, target))
        self.assertNotEqual(original, postgres._target_fingerprint(params, source, {**target, "oid": 3}))
        self.assertNotEqual(original, postgres._target_fingerprint({**params, "host": "another-db"}, source, target))

    def test_native_parameters_follow_the_effective_selected_database(self):
        backend = Mock()
        backend.vendor = "postgresql"
        backend.settings_dict = {"NAME": "original_deployment_database"}
        backend.connection.get_dsn_parameters.return_value = {
            "dbname": "original_deployment_database", "host": "configured-cluster",
            "port": "5432", "sslmode": "verify-full", "sslcertmode": "allow",
        }
        backend.get_connection_params.return_value = {
            "dbname": "selected_restored_database", "user": "operator", "password": "private-password",
            "sslrootcert": "/private/root.crt",
        }
        with patch.object(postgres, "connection", backend):
            actual = postgres._params()
        backend.ensure_connection.assert_called_once_with()
        self.assertEqual(actual["dbname"], "selected_restored_database")
        self.assertEqual(actual["host"], "configured-cluster")
        self.assertEqual(actual["sslmode"], "verify-full")
        self.assertEqual(actual["sslrootcert"], "/private/root.crt")
        self.assertNotIn("sslcertmode", actual)  # New libpq defaults need not exist in pg_dump14.

    def test_backup_never_overwrites_a_retained_dump(self):
        path = self.directory / "archive.dump"
        path.write_bytes(b"retained backup")

        @contextmanager
        def database(*args, **kwargs):
            yield object(), {"server_major": 14, "snapshot": "1-2-3"}

        with patch.object(postgres, "_params", return_value={}), patch.object(postgres, "_database", database), patch.object(postgres, "_toolchain", return_value={}), patch.object(postgres, "_inventory", return_value={}):
            with self.assertRaisesMessage(TransferError, "already exists"):
                postgres.dump_to(path)
        self.assertEqual(path.read_bytes(), b"retained backup")

    def test_schema_verification_normalizes_only_equivalent_literal_text_array_coercion(self):
        source = b" CONSTRAINT example CHECK (kind = ANY ((ARRAY['a'::character varying, 'b,c'::character varying])::text[])))\n"
        restored = b" CONSTRAINT example CHECK (kind = ANY (ARRAY[('a'::character varying)::text, ('b,c'::character varying)::text])))\n"
        self.assertEqual(postgres._canonical_constraint_line(source), restored)
        self.assertEqual(postgres._canonical_constraint_line(restored), restored)
        changed_value = restored.replace(b"'a'", b"'different value'")
        self.assertNotEqual(postgres._canonical_constraint_line(source),
                            postgres._canonical_constraint_line(changed_value))
        self.assertNotEqual(
            postgres._canonical_constraint_line(b" CONSTRAINT example CHECK (amount::numeric(3,1) > 0)\n"),
            postgres._canonical_constraint_line(b" CONSTRAINT example CHECK (amount::numeric(4,1) > 0)\n"),
        )
        for expression in (b" CONSTRAINT example CHECK ((amount::numeric(3,1)) > 0)\n",
                           b" CONSTRAINT example CHECK (kind = ANY ((ARRAY[column_value])::text[])))\n",
                           b" SELECT '(ARRAY[example])::text[]';\n"):
            self.assertEqual(postgres._canonical_constraint_line(expression), expression)


@skipUnless(connection.vendor == "postgresql", "Native restore requires disposable PostgreSQL")
@override_settings(QC_TOOL_TRANSFER_MIN_FREE_BYTES=1024**2)
class NativePostgresRoundTripTests(TransactionTestCase):
    """Targets are test-owned databases, never an existing application DB."""

    def setUp(self):
        from psycopg2 import sql

        name = str(connection.settings_dict["NAME"])
        self.assertTrue(name.startswith("test_") or re.fullmatch(r"qc_native_helpers_[0-9a-f]{12}", name),
                        "Refusing native fixture DDL outside Django's disposable test database")
        self.directory = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(override_settings(QC_TOOL_TRANSFER_DIR=self.directory / "operations"))
        self.target = "qc_native_test_" + uuid4().hex
        self.enterContext(override_settings(QC_TOOL_RESTORE_DATABASE=self.target))
        self.assertTrue(postgres.availability()["available"], postgres.availability()["reason"])
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(self.target)))
        self.addCleanup(self.drop_target)

    def drop_target(self):
        from psycopg2 import sql

        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(self.target)))

    def make_package(self):
        dump = self.directory / (uuid4().hex + ".dump")
        records = postgres.dump_to(dump)
        path = self.directory / (uuid4().hex + ".zip")
        write_archive(path, {}, records, (ArtifactSource("database", "archive.dump", dump),))
        self.assertEqual(stat.S_IMODE(dump.stat().st_mode), 0o600)
        return inspect_archive(path)

    @contextmanager
    def target_connection(self, destination=None):
        import psycopg2

        handle = psycopg2.connect(**{**postgres._params(), "dbname": destination or self.target})
        try:
            yield handle
        finally:
            handle.close()

    def new_restore_operation(self):
        from qc_tool.database.transfers import store

        operation_id = str(uuid4())
        name = postgres.restore_database_name(operation_id)
        with connection.cursor() as cursor:
            cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname=%s)", [name])
            self.assertFalse(cursor.fetchone()[0])
        store.operation_dir(operation_id, create=True)
        self.addCleanup(self.remove_prepared_database, name)
        return operation_id, name

    def remove_prepared_database(self, name):
        from psycopg2 import sql

        self.assertRegex(name, r"\Aqc_restore_[0-9a-f]{32}\Z")
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))

    def prepare(self, verified, operation_id):
        from qc_tool.database.transfers import store

        with store.execution_lock():
            return postgres.prepare_restore_target(verified, operation_id)

    def test_administrator_prepares_matching_database_and_restores_without_environment_configuration(self):
        from qc_tool.database.transfers import store

        verified = self.make_package()
        source_before = postgres.preview()["review_hash"]
        operation_id, name = self.new_restore_operation()
        with override_settings(QC_TOOL_RESTORE_DATABASE=""):
            prepared = self.prepare(verified, operation_id)
            self.assertTrue(prepared["created"])
            self.assertTrue(prepared["ready"])
            self.assertEqual(prepared["database"], name)
            plan = postgres.plan_restore(verified, name)
            self.assertTrue(plan["can_apply"])
            self.assertEqual(plan["target_fingerprint"], prepared["target_fingerprint"])
            self.assertTrue(postgres.restore(verified, prepared["target_fingerprint"], name)["verified"])
            self.assertTrue(postgres.verify_restore(verified, prepared["target_fingerprint"], name)["verified"])
            repeated = self.prepare(verified, operation_id)
            self.assertFalse(repeated["created"])
            self.assertEqual(repeated["target_oid"], prepared["target_oid"])
        journal = store.operation_dir(operation_id) / "restore-target.json"
        self.assertEqual(stat.S_IMODE(journal.stat().st_mode), 0o600)
        self.assertNotIn("marker", prepared)
        self.assertEqual(postgres.preview()["review_hash"], source_before)

    def test_preparation_never_adopts_an_unowned_existing_database(self):
        from psycopg2 import sql

        verified = self.make_package()
        operation_id, name = self.new_restore_operation()
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
        with self.target_connection(name) as target, target.cursor() as cursor:
            cursor.execute("CREATE TABLE retained_record(value text)")
            cursor.execute("INSERT INTO retained_record VALUES ('preserve existing database')")
            target.commit()
        with self.assertRaisesMessage(TransferError, "already exists"):
            self.prepare(verified, operation_id)
        with self.target_connection(name) as target, target.cursor() as cursor:
            cursor.execute("SELECT value FROM retained_record")
            self.assertEqual(cursor.fetchone()[0], "preserve existing database")

    def test_failed_create_retains_intent_and_can_retry_when_no_database_exists(self):
        import psycopg2

        verified = self.make_package()
        operation_id, _name = self.new_restore_operation()
        with patch.object(postgres, "_create_database", side_effect=psycopg2.OperationalError("password=private-value")):
            with self.assertRaises(TransferError) as raised:
                self.prepare(verified, operation_id)
        self.assertNotIn("private-value", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertTrue(self.prepare(verified, operation_id)["created"])

    def test_lost_create_acknowledgement_preserves_unmarked_database_and_refuses_adoption(self):
        import psycopg2

        verified = self.make_package()
        operation_id, name = self.new_restore_operation()
        real_create = postgres._create_database

        def lost_ack(cursor, database, source):
            real_create(cursor, database, source)
            raise psycopg2.OperationalError("injected lost CREATE acknowledgement")

        with patch.object(postgres, "_create_database", side_effect=lost_ack):
            with self.assertRaises(TransferError):
                self.prepare(verified, operation_id)
        with self.assertRaisesMessage(TransferError, "could not prove ownership"):
            self.prepare(verified, operation_id)
        with connection.cursor() as cursor:
            cursor.execute("SELECT datallowconn,shobj_description(oid,'pg_database') FROM pg_database WHERE datname=%s", [name])
            self.assertEqual(cursor.fetchone(), (False, None))

    def test_ownership_marker_recovers_a_lost_private_journal_acknowledgement(self):
        from qc_tool.database.transfers import store

        verified = self.make_package()
        operation_id, name = self.new_restore_operation()
        write = store.write_json

        def lost_ack(path, journal):
            if journal.get("status") == "owned":
                raise OSError("injected ownership journal failure")
            return write(path, journal)

        with patch.object(store, "write_json", side_effect=lost_ack):
            with self.assertRaises(TransferError):
                self.prepare(verified, operation_id)
        with connection.cursor() as cursor:
            cursor.execute("SELECT oid,datallowconn FROM pg_database WHERE datname=%s", [name])
            original_oid, allowed = cursor.fetchone()
        self.assertFalse(allowed)
        with patch.object(postgres, "_create_database") as create:
            prepared = self.prepare(verified, operation_id)
        create.assert_not_called()
        self.assertEqual(prepared["target_oid"], original_oid)
        self.assertTrue(prepared["ready"])

    def test_lost_final_journal_acknowledgement_reuses_the_same_owned_database(self):
        from qc_tool.database.transfers import store

        verified = self.make_package()
        operation_id, name = self.new_restore_operation()
        write = store.write_json

        def lost_ack(path, journal):
            if journal.get("status") == "ready":
                raise OSError("injected final journal failure")
            return write(path, journal)

        with patch.object(store, "write_json", side_effect=lost_ack):
            with self.assertRaises(TransferError):
                self.prepare(verified, operation_id)
        with connection.cursor() as cursor:
            cursor.execute("SELECT oid,datallowconn FROM pg_database WHERE datname=%s", [name])
            original_oid, allowed = cursor.fetchone()
        self.assertTrue(allowed)
        with patch.object(postgres, "_create_database") as create:
            prepared = self.prepare(verified, operation_id)
        create.assert_not_called()
        self.assertEqual(prepared["target_oid"], original_oid)

    def test_missing_createdb_privilege_is_reported_without_creating_a_database(self):
        verified = self.make_package()
        operation_id, name = self.new_restore_operation()
        with connection.cursor() as cursor:
            cursor.execute("SELECT oid FROM pg_roles WHERE rolname=current_user")
            owner = cursor.fetchone()[0]
        with patch.object(postgres, "_creation_role", return_value=(owner, False)), patch.object(postgres, "_create_database") as create:
            self.assertFalse(postgres.availability()["can_create_restore"])
            with self.assertRaisesMessage(TransferError, "CREATEDB permission"):
                self.prepare(verified, operation_id)
        create.assert_not_called()
        with connection.cursor() as cursor:
            cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname=%s)", [name])
            self.assertFalse(cursor.fetchone()[0])

    def test_a_replaced_prepared_database_is_preserved_and_not_adopted(self):
        from psycopg2 import sql

        verified = self.make_package()
        operation_id, name = self.new_restore_operation()
        prepared = self.prepare(verified, operation_id)
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            cursor.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
            cursor.execute("SELECT oid FROM pg_database WHERE datname=%s", [name])
            self.assertNotEqual(cursor.fetchone()[0], prepared["target_oid"])
        with self.assertRaisesMessage(TransferError, "could not prove ownership"):
            self.prepare(verified, operation_id)

    def test_full_native_round_trip_preserves_credentials_extra_columns_tables_sequences_and_large_objects(self):
        user = get_user_model().objects.create_superuser("native-owner", "native@example.test", "original-password")
        token = PersonalAccessToken.objects.create(user=user, name="native-api-token", secret_digest="sha256:" + "d" * 64,
            token_hint="fixture", permission_snapshot=["run_quality_control"], role_snapshot=["Admin"],
            product_idents_snapshot=["fixture-product"], is_administrator_snapshot=True)
        Session.objects.create(session_key="native-test-session", session_data="retained-session-bytes", expire_date=timezone.now())
        with connection.cursor() as cursor:
            cursor.execute("CREATE TABLE qc_native_extra (id bigserial PRIMARY KEY, extra text, payload bytea, amount numeric)")
            cursor.execute("INSERT INTO qc_native_extra(extra,payload,amount) VALUES (%s,%s,%s)", ["original\nbytes", b"\x00\xff", "12.3400"])
            cursor.execute("ALTER TABLE auth_user ADD COLUMN qc_native_unmanaged text DEFAULT 'additional stored field'")
            cursor.execute("CREATE MATERIALIZED VIEW qc_native_unpopulated AS SELECT * FROM qc_native_extra WITH NO DATA")
            cursor.execute("SELECT setval('qc_native_extra_id_seq', 401, false)")
        self.addCleanup(self.remove_extra_objects)
        with transaction.atomic():
            large_object = connection.connection.lobject(0, "wb")
            oid = large_object.oid
            large_object.write(b"complete large object bytes\x00\xff")
            large_object.close()
        self.addCleanup(self.remove_large_object, oid)
        verified = self.make_package()
        preview = postgres.plan_restore(verified)
        self.assertTrue(preview["can_apply"], preview["blockers"])
        result = postgres.restore(verified, preview["target_fingerprint"])
        self.assertTrue(result["verified"])
        with self.target_connection() as target, target.cursor() as cursor:
            cursor.execute("SELECT password,is_superuser,is_staff,is_active,qc_native_unmanaged FROM auth_user WHERE id=%s", [user.pk])
            self.assertEqual(cursor.fetchone(), (user.password, True, True, True, "additional stored field"))
            cursor.execute("SELECT secret_digest,permission_snapshot,role_snapshot,product_idents_snapshot,is_administrator_snapshot FROM account_api_token WHERE id=%s", [token.pk])
            self.assertEqual(cursor.fetchone(), (token.secret_digest, token.permission_snapshot, token.role_snapshot, token.product_idents_snapshot, True))
            cursor.execute("SELECT session_data FROM django_session WHERE session_key='native-test-session'")
            self.assertEqual(cursor.fetchone()[0], "retained-session-bytes")
            cursor.execute("SELECT extra,payload,amount::text FROM qc_native_extra")
            extra, binary, amount = cursor.fetchone()
            self.assertEqual((extra, bytes(binary), amount), ("original\nbytes", b"\x00\xff", "12.3400"))
            cursor.execute("SELECT last_value,is_called FROM qc_native_extra_id_seq")
            self.assertEqual(cursor.fetchone(), (401, False))
            cursor.execute("SELECT lo_get(%s)", [oid])
            self.assertEqual(bytes(cursor.fetchone()[0]), b"complete large object bytes\x00\xff")
        # Retry after a lost acknowledgement verifies the occupied exact copy;
        # it does not run pg_restore again or duplicate imported rows.
        self.assertEqual(postgres.restore(verified, preview["target_fingerprint"]), result)
        self.assertFalse(postgres.plan_restore(verified)["can_apply"])

    def remove_extra_objects(self):
        with connection.cursor() as cursor:
            cursor.execute("DROP MATERIALIZED VIEW IF EXISTS qc_native_unpopulated")
            cursor.execute("DROP TABLE IF EXISTS qc_native_extra")
            cursor.execute("ALTER TABLE auth_user DROP COLUMN IF EXISTS qc_native_unmanaged")

    def remove_large_object(self, oid):
        with connection.cursor() as cursor:
            cursor.execute("SELECT lo_unlink(%s)", [oid])

    def test_current_and_populated_targets_are_refused_without_clearing_anything(self):
        verified = self.make_package()
        with override_settings(QC_TOOL_RESTORE_DATABASE=connection.settings_dict["NAME"]):
            with self.assertRaisesMessage(TransferError, "connected application database"):
                postgres.plan_restore(verified)
        preview = postgres.plan_restore(verified)
        with self.target_connection() as target, target.cursor() as cursor:
            cursor.execute("CREATE TABLE retained_private_data(value text)")
            cursor.execute("INSERT INTO retained_private_data VALUES ('keep original')")
            target.commit()
        self.assertFalse(postgres.plan_restore(verified)["can_apply"])
        with self.assertRaisesMessage(TransferError, "does not exactly match"):
            postgres.restore(verified, preview["target_fingerprint"])
        with self.target_connection() as target, target.cursor() as cursor:
            cursor.execute("SELECT value FROM retained_private_data")
            self.assertEqual(cursor.fetchone()[0], "keep original")

    def test_an_empty_target_with_another_backend_cannot_be_planned_or_restored(self):
        verified = self.make_package()
        preview = postgres.plan_restore(verified)
        with self.target_connection() as other:
            with other.cursor() as cursor:
                cursor.execute("SELECT 1")
            for action in (lambda: postgres.plan_restore(verified),
                           lambda: postgres.restore(verified, preview["target_fingerprint"]),
                           lambda: postgres.verify_restore(verified, preview["target_fingerprint"])):
                with self.assertRaisesMessage(TransferError, "another connected client"):
                    action()
        self.assertTrue(postgres.plan_restore(verified)["can_apply"])

    def test_public_collation_alone_makes_a_target_occupied(self):
        verified = self.make_package()
        with self.target_connection() as target, target.cursor() as cursor:
            cursor.execute('CREATE COLLATION public.retained_collation FROM "C"')
            target.commit()
        self.assertFalse(postgres.plan_restore(verified)["can_apply"])

    def test_changed_target_identity_and_changed_restored_values_fail_closed(self):
        verified = self.make_package()
        preview = postgres.plan_restore(verified)
        with self.assertRaisesMessage(TransferError, "identity changed"):
            postgres.restore(verified, "0" * 64)
        postgres.restore(verified, preview["target_fingerprint"])
        with self.target_connection() as target, target.cursor() as cursor:
            cursor.execute("INSERT INTO auth_group(name) VALUES ('Unexpected target change')")
            target.commit()
        with self.assertRaisesMessage(TransferError, "does not exactly match"):
            postgres.verify_restore(verified, preview["target_fingerprint"])
        with self.assertRaisesMessage(TransferError, "does not exactly match"):
            postgres.restore(verified, preview["target_fingerprint"])

    def test_real_background_service_exports_stages_and_restores_the_complete_database(self):
        self.service_round_trip()

    def test_real_service_preserves_complete_database_with_optional_unlinked_zip(self):
        self.service_round_trip(include_files=True)

    def service_round_trip(self, *, include_files=False):
        from qc_tool.database.transfers import service
        from qc_tool.common import CONFIG

        self.enterContext(override_settings(
            QC_TOOL_MAINTENANCE_DIR=self.directory / "maintenance",
            QC_TOOL_TRANSFER_DIR=self.directory / "transfers", MAINTENANCE_MODE=False,
        ))
        self.enterContext(patch.object(service, "_launch"))
        actor = get_user_model().objects.create_superuser("native-service-operator", "operator@example.test", "operator-password")
        enabled = maintenance.enable(actor, 0)
        generation = enabled["generation"]
        self.assertEqual(maintenance.advance(generation)["phase"], "ready")
        original = postgres.preview()
        selection = {"profile": "database", "user_ids": [], "include_files": include_files}
        if include_files:
            source = {name: self.directory / ("source-" + name) for name in (
                "work_dir", "incoming_dir", "submission_dir", "boundary_dir")}
            for path in source.values():
                path.mkdir()
            source["product_dirs"] = []
            self.enterContext(patch.dict(CONFIG, source))
            owner = source["incoming_dir"] / "retained-owner"
            owner.mkdir()
            (owner / "retained.zip").write_bytes(b"original retained input")
        reviewed = service.export_preview(selection, actor)
        exported = service.create_export(selection, actor, reviewed["review_hash"], generation)
        self.assertEqual(active_operation()["operation_id"], exported["id"])
        self.assertEqual(service.run_operation(exported["id"])["status"], "completed")
        self.assertIsNone(active_operation())
        stream, _download = service.download_operation(exported["id"], actor)
        with stream:
            uploaded = SimpleUploadedFile("complete-postgresql.zip", stream.read())
        if include_files:
            target_files = {name: self.directory / ("target-" + name) for name in (
                "work_dir", "incoming_dir", "submission_dir", "boundary_dir")}
            CONFIG.update(target_files)
            self.enterContext(override_settings(MEDIA_ROOT=target_files["incoming_dir"]))
        staged = service.stage_import(uploaded, actor)
        self.assertEqual(staged["profile"], "database")
        planned = service.plan_import(staged["id"], actor)
        self.assertTrue(planned["can_apply"], planned["blockers"])
        queued = service.start_import(staged["id"], actor, planned["plan_hash"], generation, confirmed_scope=True)
        self.assertEqual(active_operation()["operation_id"], queued["id"])
        restored = service.run_operation(queued["id"])
        self.assertEqual(restored["status"], "completed")
        self.assertTrue(restored["result"]["verified"])
        self.assertEqual(restored["result"]["counts"], original["counts"])
        self.assertEqual(postgres.preview()["review_hash"], original["review_hash"])
        self.assertIsNone(active_operation())
        self.assertTrue(maintenance.read_status()["enabled"])
        if include_files:
            restored_zip = target_files["incoming_dir"] / "retained-owner" / "retained.zip"
            self.assertEqual(restored_zip.read_bytes(), b"original retained input")
            self.assertTrue(restored["result"]["include_files"])
            from qc_tool.frontend.dashboard.services.storage_admin.references import describe_references
            usage = describe_references("incoming", "retained-owner/retained.zip")
            self.assertTrue(usage["protected"])
            self.assertFalse(usage["can_quarantine"])
