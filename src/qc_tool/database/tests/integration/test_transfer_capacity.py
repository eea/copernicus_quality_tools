"""Real large-catalog exports, using only disposable SQL and file storage."""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from qc_tool.database.tests.integration import test_transfer_application as fixtures
from qc_tool.database.transfers import service, store
from qc_tool.database.transfers.archive import inspect_archive
from qc_tool.database.transfers.records import validate_records
from qc_tool.frontend.dashboard.models import ProductRelease, ProductUnit


class LargeRecordPackageTests(TestCase):
    setUp = fixtures.ApplicationTransferIntegrationTests.setUp
    configuration = fixtures.ApplicationTransferIntegrationTests.configuration
    make_graph = fixtures.ApplicationTransferIntegrationTests.make_graph

    @override_settings(QC_TOOL_TRANSFER_MAX_RECORDS=250_000)
    def test_catalog_above_old_limit_exports_every_unit_and_remains_readable(self):
        # The reported installation has 130,238 units. Exercise that actual
        # cardinality, including the original job/publication's unit, through
        # the service and archive reader rather than mocking a row count.
        release = ProductRelease.objects.get()
        for start in range(0, 130_237, 1_000):
            ProductUnit.objects.bulk_create([
                ProductUnit(product_release=release, product_unit_code=f"unit-{index:06d}", provenance="fixture")
                for index in range(start, min(start + 1_000, 130_237))
            ])
        selection = {"profile": "application", "user_ids": [], "include_files": False}
        preview = service.export_preview(selection, self.actor)
        self.assertEqual(preview["counts"]["units"], 130_238)
        self.assertGreater(preview["total_records"], 100_000)
        self.assertEqual(preview["record_limit"], 250_000)
        self.assertFalse(preview["blockers"], preview["blockers"])
        operation = service.create_export(selection, self.actor, preview["review_hash"], self.generation)
        completed = service.run_operation(operation["id"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["result"]["counts"]["units"], 130_238)
        archive = inspect_archive(store.operation_dir(operation["id"]) / "package.zip")
        payload = validate_records(archive.records)
        self.assertEqual(len(payload["records"]["units"]), 130_238)
        self.assertEqual({row["product_unit_code"] for row in payload["records"]["units"]},
                         set(ProductUnit.objects.values_list("product_unit_code", flat=True)))
        self.assertEqual(len(payload["provenance"]["identities"]["units"]), 130_238)
        self.assertFalse(archive.entries)
        self.assertTrue(archive.storage["references"]["items"])
        # Simulate a destination missing the extra catalog entries, exclusively
        # in this disposable fixture. A usable export must also fit its durable
        # import review, which previously duplicated all pending record rows.
        ProductUnit.objects.filter(product_unit_code__startswith="unit-")._raw_delete("default")
        staged = service.stage_import(SimpleUploadedFile(
            "large-records.zip", (store.operation_dir(operation["id"]) / "package.zip").read_bytes(),
        ), self.actor, include_files=False)
        plan = service.plan_import(staged["id"], self.actor, {
            str(self.actor.pk): self.actor.pk, str(self.owner.pk): self.owner.pk,
        })
        self.assertTrue(plan["can_apply"], plan["blockers"])
        units = next(row for row in plan["resource_summary"] if row["resource"] == "units")
        self.assertEqual(units["create"], 130_237)
        self.assertEqual(units["reuse"], 1)
        self.assertEqual(store.read_operation(staged["id"])["status"], "planned")
        self.assertLess((store.operation_dir(staged["id"]) / "operation.json").stat().st_size,
                        store.MAX_JOURNAL_BYTES)
