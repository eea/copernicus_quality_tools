"""Operator-facing legacy import safeguards, using a synthetic COPY dump."""

from io import StringIO
import json
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, DatabaseError
from django.test import TestCase, override_settings

from qc_tool.database.legacy.importer import prepare_import
from qc_tool.database.tests.integration.test_legacy_import import synthetic_legacy_dump
from qc_tool.frontend.dashboard.models import Delivery, Job


_COMMAND_MODULE = "qc_tool.database.management.commands.import_legacy_dump"


def write_synthetic_copy_dump(path, dump):
    def encode(value):
        if value is None:
            return "\\N"
        return value.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")

    lines = ["-- PostgreSQL database dump", "SET client_encoding = 'UTF8';"]
    for table, columns in dump.columns.items():
        lines.append(f"COPY public.{table} ({', '.join(columns)}) FROM stdin;")
        lines.extend("\t".join(encode(row[column]) for column in columns) for row in dump.tables[table])
        lines.append("\\.")
    lines.append("-- PostgreSQL database dump complete")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@override_settings(USE_TZ=False, TIME_ZONE="Europe/Prague")
class LegacyImportCommandTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password_hash = make_password("synthetic-command-password")

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.dump = synthetic_legacy_dump(self.password_hash)
        self.source = self.directory / "synthetic.sql"
        write_synthetic_copy_dump(self.source, self.dump)
        self.output = StringIO()

    def command(self, *arguments):
        call_command("import_legacy_dump", str(self.source), *arguments, stdout=self.output)

    def apply_arguments(self):
        return ("--apply", "--target-database", str(connection.settings_dict["NAME"]))

    def test_default_dry_run_reads_dump_without_target_queries_or_writes(self):
        with self.assertNumQueries(0):
            self.command()
        report = json.loads(self.output.getvalue())
        self.assertEqual(report["mode"], "dry_run")
        self.assertEqual(report["planned"]["users"], 1)
        self.assertEqual(report["planned"]["deliveries"], 2)
        self.assertFalse(get_user_model().objects.exists())
        self.assertFalse(Delivery.objects.exists())

    def test_explicit_dry_run_does_not_consult_database_alias(self):
        with self.assertNumQueries(0):
            self.command("--dry-run", "--database", "does-not-exist")
        self.assertEqual(json.loads(self.output.getvalue())["mode"], "dry_run")

    def test_apply_requires_explicit_target_before_reading_source(self):
        with patch(f"{_COMMAND_MODULE}.read_legacy_dump") as read_dump:
            with self.assertRaisesRegex(CommandError, "requires --target-database"):
                self.command("--apply")
        read_dump.assert_not_called()
        self.assertFalse(get_user_model().objects.exists())

    def test_apply_rejects_wrong_target_without_queries_or_writes(self):
        with self.assertNumQueries(0), self.assertRaisesRegex(CommandError, "does not match"):
            self.command("--apply", "--target-database", "definitely-not-the-configured-target")
        self.assertFalse(get_user_model().objects.exists())

    def test_apply_with_correct_target_imports_synthetic_source_and_prints_counts(self):
        self.command(*self.apply_arguments())
        report = json.loads(self.output.getvalue())
        self.assertEqual(report["mode"], "applied")
        self.assertEqual(report["imported"]["users"], 1)
        self.assertEqual(report["imported"]["deliveries"], 2)
        self.assertEqual(report["imported"]["jobs"], 1)
        self.assertTrue(get_user_model().objects.get(pk=47).check_password("synthetic-command-password"))
        self.assertEqual(Delivery.objects.count(), 2)
        self.assertEqual(Job.objects.count(), 1)
        for secret in (self.password_hash, "synthetic-api-secret", "synthetic-storage-secret", "legacy-owner@example.invalid"):
            self.assertNotIn(secret, self.output.getvalue())

    def test_new_report_is_private_and_matches_stdout(self):
        report_path = self.directory / "report.json"
        self.command("--report", str(report_path))
        self.assertEqual(stat.S_IMODE(report_path.stat().st_mode), 0o600)
        self.assertEqual(json.loads(report_path.read_text()), json.loads(self.output.getvalue()))
        self.assertFalse(get_user_model().objects.exists())

    def test_existing_report_is_never_overwritten_and_blocks_apply_before_reading_dump(self):
        report_path = self.directory / "report.json"
        original = b"Existing operator record\n"
        report_path.write_bytes(original)
        with patch(f"{_COMMAND_MODULE}.read_legacy_dump") as read_dump:
            with self.assertRaisesRegex(CommandError, "already exists"):
                self.command(*self.apply_arguments(), "--report", str(report_path))
        read_dump.assert_not_called()
        self.assertEqual(report_path.read_bytes(), original)
        self.assertFalse(get_user_model().objects.exists())

    def test_dangling_report_symlink_is_rejected_before_import(self):
        target = self.directory / "not-created.json"
        report_path = self.directory / "report.json"
        report_path.symlink_to(target)
        with self.assertRaisesRegex(CommandError, "already exists"):
            self.command(*self.apply_arguments(), "--report", str(report_path))
        self.assertFalse(target.exists())
        self.assertFalse(get_user_model().objects.exists())

    def test_missing_report_directory_prevents_import(self):
        with self.assertRaisesRegex(CommandError, "directory does not exist"):
            self.command(*self.apply_arguments(), "--report", str(self.directory / "missing" / "report.json"))
        self.assertFalse(get_user_model().objects.exists())

    def test_database_error_never_prints_driver_source_rows(self):
        with patch(f"{_COMMAND_MODULE}.apply_import", side_effect=DatabaseError("synthetic-private-database-row")):
            with self.assertRaisesRegex(CommandError, "failed and was rolled back") as caught:
                self.command(*self.apply_arguments())
        self.assertNotIn("synthetic-private-database-row", str(caught.exception))
        self.assertEqual(self.output.getvalue(), "")

    def test_malformed_access_map_errors_do_not_echo_source_text(self):
        access_map = self.directory / "access.json"
        access_map.write_text('{"users": synthetic-private-map-content}', encoding="utf-8")
        with self.assertNumQueries(0), self.assertRaisesRegex(CommandError, "not valid JSON") as caught:
            self.command(*self.apply_arguments(), "--access-map", str(access_map))
        self.assertNotIn("synthetic-private-map-content", str(caught.exception))
        self.assertFalse(get_user_model().objects.exists())

    def test_invalid_access_map_role_is_sanitized_and_blocks_import(self):
        access_map = self.directory / "access.json"
        access_map.write_text(json.dumps({"users": {"47": {"roles": ["synthetic-private-role"]}}}), encoding="utf-8")
        with self.assertNumQueries(0), self.assertRaises(CommandError) as caught:
            self.command(*self.apply_arguments(), "--access-map", str(access_map))
        self.assertNotIn("synthetic-private-role", str(caught.exception))
        self.assertFalse(get_user_model().objects.exists())

    def test_report_write_failure_after_apply_clearly_reports_committed_import(self):
        with patch(f"{_COMMAND_MODULE}.os.open", side_effect=PermissionError("Cannot create report")):
            with self.assertRaisesRegex(CommandError, "Import committed, but the report file could not be written"):
                self.command(*self.apply_arguments(), "--report", str(self.directory / "report.json"))
        self.assertEqual(json.loads(self.output.getvalue())["mode"], "applied")
        self.assertEqual(Delivery.objects.count(), 2)

    def test_unknown_job_status_is_rejected_without_echoing_the_source_value(self):
        self.dump.tables["dashboard_job"][0]["job_status"] = "synthetic-private-status"
        with self.assertNumQueries(0), self.assertRaises(ValueError) as caught:
            prepare_import(self.dump)
        self.assertNotIn("synthetic-private-status", str(caught.exception))
        write_synthetic_copy_dump(self.source, self.dump)
        with self.assertNumQueries(0), self.assertRaises(CommandError) as caught:
            self.command(*self.apply_arguments())
        self.assertNotIn("synthetic-private-status", str(caught.exception))
        self.assertFalse(get_user_model().objects.exists())
