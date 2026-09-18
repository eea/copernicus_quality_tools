"""Import executable JSON snapshots and draft product unit scopes explicitly."""

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from qc_tool.frontend.dashboard.services.catalog.definition_import import (
    synchronize_definition_directories,
)
from qc_tool.frontend.dashboard.services.catalog.errors import CatalogError


class Command(BaseCommand):
    help = "Store definition JSON revisions and declared product unit scopes for product reporting."

    def add_arguments(self, parser):
        parser.add_argument(
            "directories",
            nargs="+",
            help="Directories containing definition JSON files.",
        )
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate and preview changes without committing them.",
        )
        mode.add_argument(
            "--check",
            action="store_true",
            help="Do not write; fail if import would change the database.",
        )

    def handle(self, *args, **options):
        try:
            result = synchronize_definition_directories(
                options["directories"],
                dry_run=options["dry_run"] or options["check"],
            )
        except CatalogError as exc:
            raise CommandError("{}: {}".format(exc.code, exc.message)) from exc
        catalog = result.catalog
        self.stdout.write(
            "{}: definitions={}, new_revisions={}, products_created={}, "
            "products_updated={}, releases_created={}, product_units_created={}, "
            "current_changes={}, managed_scopes_retained={}, "
            "unknown_scopes={}.".format(
                "Import preview" if options["dry_run"] or options["check"] else "Definitions synchronized",
                result.definitions_scanned,
                catalog.definitions_created,
                catalog.products_created,
                catalog.products_updated,
                catalog.releases_created,
                catalog.product_units_created,
                catalog.current_pointers_changed,
                result.managed_definitions,
                result.unknown_scopes,
            )
        )
        if options["check"] and result.changed:
            raise CommandError("The database definition catalog is out of date.")
