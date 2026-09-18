"""Publish a validated, version-controlled product catalog manifest."""

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from qc_tool.frontend.dashboard.services.catalog import CatalogError
from qc_tool.frontend.dashboard.services.catalog import load_catalog_manifest
from qc_tool.frontend.dashboard.services.catalog import synchronize_product_catalog


class Command(BaseCommand):
    help = "Synchronize immutable product-release and expected-product unit revisions."

    def add_arguments(self, parser):
        parser.add_argument("manifest", help="Path to the versioned catalog JSON.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate and report database changes without committing them.",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help="Exit unsuccessfully when synchronization would change the DB.",
        )

    def handle(self, *args, **options):
        try:
            snapshot = load_catalog_manifest(options["manifest"])
            result = synchronize_product_catalog(
                snapshot,
                dry_run=bool(options["dry_run"] or options["check"]),
            )
        except CatalogError as exc:
            raise CommandError("{}: {}".format(exc.code, exc.message)) from exc
        if options["check"] and result.changed:
            raise CommandError("The database product catalog is out of date.")
        self.stdout.write(
            self.style.SUCCESS(
                "Catalog synchronized: releases={}, definitions_created={}, "
                "products_created={}, products_updated={}, "
                "releases_created={}, product_units_created={}, current_changes={}.".format(
                    result.releases_scanned,
                    result.definitions_created,
                    result.products_created,
                    result.products_updated,
                    result.releases_created,
                    result.product_units_created,
                    result.current_pointers_changed,
                )
            )
        )
