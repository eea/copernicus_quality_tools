"""Offline conversion of a legacy pg_dump into a fresh application schema."""

import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError
from django.utils.connection import ConnectionDoesNotExist

from qc_tool.database.legacy.dump import LegacyDumpError, read_legacy_dump
from qc_tool.database.legacy.importer import apply_import, prepare_import


class Command(BaseCommand):
    help = "Audit/import an old QC Tool SQL dump. Dry run by default; SQL is never executed."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("dump", type=Path)
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--apply", action="store_true", help="Import into a fresh initialized target.")
        mode.add_argument("--dry-run", action="store_true", help="Validate and report only (the default).")
        parser.add_argument("--database", default="default", help="Django database alias.")
        parser.add_argument("--target-database", help="Exact configured database name/path, required with --apply.")
        parser.add_argument("--access-map", type=Path, help="Reviewed JSON mapping user IDs to roles/products/regions.")
        parser.add_argument("--report", type=Path, help="Write a new JSON audit report (never overwrite an existing file).")

    def handle(self, *args, **options):
        if options["apply"] and not options["target_database"]:
            raise CommandError("--apply requires --target-database with the exact configured target name/path.")
        destination = options["report"]
        if destination and (destination.exists() or destination.is_symlink()):
            raise CommandError("The report destination already exists. Choose a new path; nothing was imported.")
        if destination and not destination.parent.is_dir():
            raise CommandError("The report directory does not exist; nothing was imported.")
        try:
            access_map = None
            if options["access_map"]:
                access_map = json.loads(options["access_map"].read_text(encoding="utf-8"))
            dump = read_legacy_dump(options["dump"])
            plan = prepare_import(dump, access_map=access_map)
            report = plan.report
            if options["apply"]:
                report = apply_import(plan, database=options["database"], target_database=options["target_database"])
        except json.JSONDecodeError:
            raise CommandError("The access map is not valid JSON; nothing was imported.") from None
        except (LegacyDumpError, ValueError) as error:
            raise CommandError(str(error)) from None
        except OSError:
            raise CommandError("A source file could not be read; nothing was imported.") from None
        except ConnectionDoesNotExist:
            raise CommandError("The requested database alias is not configured; nothing was imported.") from None
        except DatabaseError:
            # SQL driver errors may contain a source row, including secrets.
            raise CommandError("Database import failed and was rolled back. Check the target schema and configuration; source rows are not printed.") from None
        serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
        self.stdout.write(serialized)
        if destination:
            try:
                descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    stream.write(serialized)
            except OSError:
                state = "Import committed" if options["apply"] else "Dry run completed"
                raise CommandError(f"{state}, but the report file could not be written. The report is printed above.") from None
