"""Database switch/rollback controls exercised only on disposable copies."""

from contextlib import ExitStack
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import PBKDF2PasswordHasher
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from qc_tool.common import CONFIG, compose_job_dir
from qc_tool.database import selection
from qc_tool.database.transfers import postgres, service, store
from qc_tool.database.transfers.errors import TransferError
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.services.users import provision_user
from qc_tool.frontend.dashboard.models import Delivery, Job
from qc_tool.frontend.dashboard.services import maintenance
from qc_tool.frontend.dashboard.services.maintenance.operations import active_operation


@override_settings(PASSWORD_HASHERS=("django.contrib.auth.hashers.MD5PasswordHasher",))
class DatabaseControlAuthorizationTests(TestCase):
    def test_every_control_refuses_nonadministrators_before_reading_or_preparing_databases(self):
        viewer = provision_user(username="control-viewer", password="viewer-password").user
        manager = provision_user(username="control-manager", password="manager-password",
                                 groups=(Role.PRODUCT_MANAGER.value,)).user
        inactive = get_user_model().objects.create_superuser("control-inactive", "", "inactive-password")
        inactive.is_active = False
        inactive.save(update_fields=("is_active",))
        for actor in (viewer, manager, inactive):
            calls = (
                lambda: service.database_control_status(actor),
                lambda: service.activation_preview("untrusted-operation", actor),
                lambda: service.prepare_restore_destination("untrusted-operation", actor),
                lambda: service.activate_database("untrusted-operation", actor,
                    review_hash="", generation=0, revision=0, destination_confirmation=""),
                lambda: service.rollback_database(actor, generation=0, revision=0, destination_confirmation=""),
                lambda: service.validate_resume_database(actor),
            )
            for action in calls:
                with self.subTest(actor=actor.username, action=action):
                    with self.assertRaisesMessage(TransferError, "active QC Tool administrator"):
                        action()


@skipUnless(connection.vendor == "postgresql", "Database activation requires disposable PostgreSQL")
@override_settings(
    PASSWORD_HASHERS=("django.contrib.auth.hashers.MD5PasswordHasher",
                      "django.contrib.auth.hashers.PBKDF2PasswordHasher"),
    QC_TOOL_TRANSFER_MIN_FREE_BYTES=1024**2, QC_TOOL_RESTORE_DATABASE="", MAINTENANCE_MODE=False,
)
class PostgreSQLDatabaseControlTests(TransactionTestCase):
    """Activate/rollback private clones, then restore the disposable test pointer."""

    password = "original-administrator-password"

    def setUp(self):
        self.source = str(connection.settings_dict["NAME"])
        self.assertTrue(self.source.startswith("test_"), "Refusing database switching fixtures outside a disposable Django test database")
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(override_settings(
            QC_TOOL_CONFIGURED_DATABASE=deepcopy(connection.settings_dict),
            QC_TOOL_TRANSFER_DIR=self.root / "transfers", QC_TOOL_MAINTENANCE_DIR=self.root / "maintenance",
        ))
        roots = {key: self.root / name for key, name in (
            ("work_dir", "work"), ("incoming_dir", "incoming"),
            ("boundary_dir", "boundaries"), ("submission_dir", "submissions"),
        )}
        for directory in roots.values():
            directory.mkdir()
        self.enterContext(patch.dict(CONFIG, {**roots, "product_dirs": []}))
        self.enterContext(patch.object(service, "_launch"))
        self.original_allowed_databases = type(self).databases
        self.original_aliases = set(connections)
        self.used_aliases = set()
        self.targets = set()
        self.actor = get_user_model().objects.create_superuser("control-administrator", "", self.password)
        self.generation = maintenance.enable(self.actor, 0)["generation"]
        self.assertEqual(maintenance.advance(self.generation)["phase"], "ready")
        self.allow_alias(self.source)

    def tearDown(self):
        # Remove only this test's pointer BEFORE Django flushes its source DB.
        # No test teardown may follow a retained/selected clone accidentally.
        (self.root / "transfers" / "database-selection.json").unlink(missing_ok=True)
        connection.close()
        for alias in self.used_aliases:
            connections[alias].close()
            if alias not in self.original_aliases:
                del connections[alias]
                connections.databases.pop(alias, None)
        type(self).databases = self.original_allowed_databases
        self.assertEqual(selection.current_database(), self.source)
        from psycopg2 import sql

        with connection.cursor() as cursor:
            for name in self.targets:
                self.assertRegex(name, r"\Aqc_restore_[0-9a-f]{32}\Z")
                cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
        super().tearDown()

    def allow_alias(self, database):
        alias = selection.alias_for_database(database)
        self.used_aliases.add(alias)
        # Django's safety wrapper reads the class allowlist at cursor time.
        # Dynamic aliases are removed again before its teardown/flush phase.
        type(self).databases = frozenset((*type(self).databases, alias))
        return alias

    def current_database(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            return cursor.fetchone()[0]

    def no_model_writes(self, action):
        def refuse_write(execute, sql, params, many, context):
            self.assertIsNone(re.match(r"\s*(?:INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|REPLACE)\b", sql, re.I),
                              f"Database control unexpectedly attempted SQL mutation on {context['connection'].alias}")
            return execute(sql, params, many, context)

        # Installing wrappers does not open idle target connections, which
        # would correctly block the native restore-isolation check.
        with ExitStack() as stack:
            for alias in {"default", *self.used_aliases}:
                stack.enter_context(connections[alias].execute_wrapper(refuse_write))
            return action()

    def external_user_change(self, database, field, value):
        """Simulate an unrelated SQL writer only against this test's databases."""
        import psycopg2
        from psycopg2 import sql

        self.assertIn(database, {self.source, *self.targets})
        self.assertIn(field, {"first_name", "is_active"})
        handle = psycopg2.connect(**{**postgres._params(), "dbname": database})
        try:
            with handle.cursor() as cursor:
                cursor.execute(sql.SQL("UPDATE auth_user SET {}=%s WHERE id=%s").format(sql.Identifier(field)),
                               [value, self.actor.pk])
            handle.commit()
        finally:
            handle.close()

    def add_report(self):
        data = b"retained synthetic original ZIP bytes"
        digest = hashlib.sha256(data).hexdigest()
        incoming = CONFIG["incoming_dir"] / self.actor.username
        incoming.mkdir()
        (incoming / "fixture.zip").write_bytes(data)
        delivery = Delivery.objects.create(user=self.actor, filename="fixture.zip", size_bytes=len(data), content_sha256=digest)
        job = Job.objects.create(delivery=delivery, job_status="ok", product_ident="fixture-product",
                                 input_sha256=digest, date_finished=timezone.now())
        directory = compose_job_dir(job.pk)
        directory.mkdir()
        report = directory / "report.pdf"
        report.write_bytes(b"original retained report")
        return report

    def completed_restore(self, *, report=False, change_source_password=False):
        report_path = self.add_report() if report else None
        choice = {"profile": "database", "user_ids": []}
        reviewed = service.export_preview(choice, self.actor)
        exported = service.create_export(choice, self.actor, reviewed["review_hash"], self.generation)
        self.assertEqual(service.run_operation(exported["id"])["status"], "completed")
        stream, _download = service.download_operation(exported["id"], self.actor)
        with stream:
            upload = SimpleUploadedFile("complete-database.zip", stream.read())
        if change_source_password:
            self.actor.set_password("changed-source-administrator-password")
            self.actor.save(update_fields=("password",))
        staged = service.stage_import(upload, self.actor)
        pending = service.plan_import(staged["id"], self.actor)
        self.assertFalse(pending["can_apply"])
        name = postgres.restore_database_name(staged["id"])
        with connection.cursor() as cursor:
            cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname=%s)", [name])
            self.assertFalse(cursor.fetchone()[0], "Refusing to reuse a preexisting target in a switching test")
        self.targets.add(name)
        prepared = service.prepare_restore_destination(staged["id"], self.actor)
        self.assertEqual(prepared["destination"]["database"], name)
        self.allow_alias(name)
        plan = service.plan_import(staged["id"], self.actor)
        self.assertTrue(plan["can_apply"], plan["blockers"])
        queued = service.start_import(staged["id"], self.actor, plan["plan_hash"], self.generation, confirmed_scope=True)
        result = service.run_operation(queued["id"])
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["result"]["verified"])
        self.assertIsNone(active_operation())
        return result, name, report_path

    def activate(self, operation, target, preview=None, **overrides):
        preview = preview or service.activation_preview(operation["id"], self.actor)
        confirmation = {"review_hash": preview["review_hash"], "generation": self.generation,
                        "revision": preview["revision"], "destination_confirmation": target,
                        "confirmed_storage": True, **overrides}
        return service.activate_database(operation["id"], self.actor, **confirmation)

    @override_settings(QC_TOOL_TRANSFER_MAX_RECORDS=1)
    def test_no_environment_restore_activation_and_rollback_retain_both_databases_without_row_writes(self):
        # Native switching is independent of portable interchange package caps.
        operation, target, _report = self.completed_restore(report=True)
        original_snapshot = postgres.preview()
        original = original_snapshot["review_hash"]
        preview = self.no_model_writes(lambda: service.activation_preview(operation["id"], self.actor))
        self.assertTrue(preview["can_apply"])
        self.assertFalse(preview["requires_credentials"])
        activated = self.no_model_writes(lambda: self.activate(operation, target, preview))
        self.assertEqual(activated["previous"], self.source)
        self.assertEqual(self.current_database(), target)
        self.assertEqual(connection.settings_dict["NAME"], self.source)
        self.no_model_writes(lambda: service.validate_resume_database(self.actor))
        self.assertEqual(postgres.preview()["inventory"], original_snapshot["inventory"])
        status = service.database_control_status(self.actor)
        self.assertEqual(status["active_database"], target)
        self.assertEqual(status["previous_database"], self.source)
        self.assertEqual(status["rollback_blockers"], [])
        rolled_back = self.no_model_writes(lambda: service.rollback_database(self.actor,
            generation=self.generation, revision=activated["revision"],
            destination_confirmation=self.source, confirmed_storage=True))
        self.assertEqual(rolled_back["previous"], target)
        self.assertEqual(self.current_database(), self.source)
        self.assertEqual(postgres.preview()["review_hash"], original)
        self.assertTrue(maintenance.read_status()["enabled"])
        self.assertEqual(maintenance.read_status()["generation"], self.generation)
        with connection.cursor() as cursor:
            cursor.execute("SELECT datname FROM pg_database WHERE datname IN (%s,%s)", [self.source, target])
            self.assertEqual({row[0] for row in cursor.fetchall()}, {self.source, target})

    def test_stale_review_revision_generation_and_missing_confirmation_cannot_switch(self):
        operation, target, _report = self.completed_restore()
        preview = service.activation_preview(operation["id"], self.actor)
        for changes in ({"revision": preview["revision"] + 1}, {"generation": self.generation + 1},
                        {"review_hash": "0" * 64}, {"confirmed_storage": False},
                        {"destination_confirmation": self.source}):
            with self.subTest(changes=changes), self.assertRaises(TransferError):
                self.activate(operation, target, preview, **changes)
            self.assertEqual(self.current_database(), self.source)
            self.assertEqual(selection.read_state()["revision"], 0)

    def test_mutated_restored_records_block_activation(self):
        operation, target, _report = self.completed_restore()
        preview = service.activation_preview(operation["id"], self.actor)
        self.external_user_change(target, "first_name", "changed after restore")
        with self.assertRaisesMessage(TransferError, "does not exactly match"):
            self.activate(operation, target, preview)
        self.assertEqual(self.current_database(), self.source)

    def test_changed_report_bytes_with_preserved_metadata_block_activation(self):
        operation, target, report = self.completed_restore(report=True)
        preview = service.activation_preview(operation["id"], self.actor)
        before = report.stat()
        original = report.read_bytes()
        report.write_bytes(b"x" * len(original))
        os.utime(report, ns=(before.st_atime_ns, before.st_mtime_ns))
        after = report.stat()
        self.assertEqual((after.st_size, after.st_ino, after.st_mtime_ns),
                         (before.st_size, before.st_ino, before.st_mtime_ns))
        with self.assertRaisesMessage(TransferError, "changed"):
            self.activate(operation, target, preview)
        self.assertEqual(self.current_database(), self.source)

    def test_different_destination_credentials_require_the_correct_password_without_auth_writes(self):
        # This valid legacy hash would be upgraded by User.check_password();
        # destination verification must use the non-writing hasher API.
        self.actor.password = PBKDF2PasswordHasher().encode(self.password, "control-legacy-salt", iterations=1)
        self.actor.save(update_fields=("password",))
        operation, target, _report = self.completed_restore(change_source_password=True)
        preview = service.activation_preview(operation["id"], self.actor)
        self.assertTrue(preview["requires_credentials"])
        for credentials in ({}, {"username": self.actor.username, "password": "incorrect"}):
            with self.subTest(credentials=tuple(credentials)), self.assertRaisesMessage(TransferError, "administrator account"):
                self.activate(operation, target, preview, **credentials)
        self.no_model_writes(lambda: self.activate(operation, target, preview,
            username=self.actor.username, password=self.password))
        self.assertEqual(self.current_database(), target)
        self.no_model_writes(lambda: service.validate_resume_database(self.actor))

    def test_revoked_destination_administrator_proof_blocks_resuming(self):
        operation, target, _report = self.completed_restore()
        self.activate(operation, target)
        self.external_user_change(target, "is_active", False)
        with self.assertRaisesMessage(TransferError, "Administrator access"):
            service.validate_resume_database(self.actor)
        self.assertTrue(maintenance.read_status()["enabled"])

    def test_rollback_refuses_a_changed_retained_database(self):
        operation, target, _report = self.completed_restore()
        activated = self.activate(operation, target)
        self.external_user_change(self.source, "first_name", "retained source changed")
        with self.assertRaisesMessage(TransferError, "retained database or its matching files changed"):
            service.rollback_database(self.actor, generation=self.generation, revision=activated["revision"],
                                      destination_confirmation=self.source, confirmed_storage=True)
        self.assertEqual(self.current_database(), target)

    def test_rollback_refuses_changed_report_bytes_even_when_metadata_is_preserved(self):
        operation, target, report = self.completed_restore(report=True)
        activated = self.activate(operation, target)
        before = report.stat()
        original = report.read_bytes()
        report.write_bytes(b"z" * len(original))
        os.utime(report, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.assertRaisesMessage(TransferError, "retained database or its matching files changed"):
            service.rollback_database(self.actor, generation=self.generation, revision=activated["revision"],
                                      destination_confirmation=self.source, confirmed_storage=True)
        self.assertEqual(self.current_database(), target)

    def test_resume_and_a_new_maintenance_generation_expire_quick_rollback(self):
        operation, target, _report = self.completed_restore()
        activated = self.activate(operation, target)
        service.validate_resume_database(self.actor)
        off = maintenance.disable(self.actor, self.generation)
        self.assertTrue(service.database_control_status(self.actor)["rollback_blockers"])
        with self.assertRaises(TransferError):
            service.rollback_database(self.actor, generation=off["generation"], revision=activated["revision"],
                                      destination_confirmation=self.source, confirmed_storage=True)
        enabled = maintenance.enable(self.actor, off["generation"])
        maintenance.advance(enabled["generation"])
        with self.assertRaisesMessage(TransferError, "Rollback is unavailable"):
            service.rollback_database(self.actor, generation=enabled["generation"], revision=activated["revision"],
                                      destination_confirmation=self.source, confirmed_storage=True)
        self.assertEqual(self.current_database(), target)

    def test_unavailable_new_database_can_return_to_its_verified_retained_source(self):
        import psycopg2
        from psycopg2 import sql

        operation, target, _report = self.completed_restore()
        activated = self.activate(operation, target)
        source_alias = self.allow_alias(self.source)
        # Recovery credentials stay tied to the retained database, matching the
        # maintenance control cookie's pinned identity after a failed switch.
        retained_actor = get_user_model().objects.using(source_alias).get(pk=self.actor.pk)
        parameters = postgres._params()
        for alias in self.used_aliases:
            connections[alias].close()
        connection.close()
        external = psycopg2.connect(**{**parameters, "dbname": self.source})
        try:
            external.autocommit = True
            with external.cursor() as cursor:
                self.assertIn(target, self.targets)
                cursor.execute(sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS false").format(sql.Identifier(target)))
        finally:
            external.close()
        rolled_back = service.rollback_database(retained_actor, generation=self.generation,
            revision=activated["revision"], destination_confirmation=self.source, confirmed_storage=True)
        self.assertEqual(rolled_back["active"], self.source)
        self.assertEqual(rolled_back["previous"], target)
        self.assertEqual(self.current_database(), self.source)
        service.validate_resume_database(retained_actor)
        self.assertTrue(maintenance.read_status()["enabled"])
        self.assertTrue(service.database_control_status(retained_actor)["rollback_blockers"])
        with connection.cursor() as cursor:
            cursor.execute("SELECT datallowconn FROM pg_database WHERE datname=%s", [target])
            self.assertEqual(cursor.fetchone(), (False,))
