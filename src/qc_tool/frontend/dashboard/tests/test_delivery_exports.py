"""Downloads include the public schema within the authorized delivery scope."""

import csv
import io
import json
from unittest.mock import patch
from xml.etree import ElementTree

import openpyxl
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from qc_tool.common import JOB_FAILED, JOB_OK, JOB_RUNNING
from qc_tool.frontend.accounts.models import UserProductGrant, UserProfile, UserRegionGrant
from qc_tool.frontend.dashboard.models import (
    Delivery, DeliverySubmission, Job, Product, ProductUnit, ProductRelease,
    SubmissionReviewEvent,
)
from qc_tool.frontend.dashboard.services.exports import EXPORT_FORMATS
from qc_tool.frontend.dashboard.views.deliveries.listing.workbook import DELIVERY_EXPORT_COLUMNS


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class DeliveryExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="export-owner")
        UserProductGrant.objects.create(user=cls.user, product_ident="test")
        cls.other = get_user_model().objects.create_user(username="other-export-owner")

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("export_deliveries_excel")

    def delivery(self, name, *, user=None, status=None, **fields):
        delivery = Delivery.objects.create(
            user=user or self.user, filename=name, size_bytes=1024,
            product_ident="test", product_description="Test product", **fields,
        )
        if status is not None:
            Job.objects.create(delivery=delivery, job_status=status, product_ident="test")
        return delivery

    def export(self, format="csv", **parameters):
        response = self.client.get(self.url, {"format": format, **parameters})
        self.assertEqual(response.status_code, 200)
        self.assertIn(f"deliveries.{format}", response["Content-Disposition"])
        content = b"".join(response.streaming_content)
        if format == "json":
            self.assertEqual(response["Content-Type"], "application/json; charset=utf-8")
            return json.loads(content)
        if format == "xml":
            self.assertEqual(response["Content-Type"], "application/xml; charset=utf-8")
            return ElementTree.fromstring(content)
        if format == "csv":
            return list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
        workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
        try:
            return [list(row) for row in workbook.active.values]
        finally:
            workbook.close()

    def table_rows(self, format, **parameters):
        """Compare records across formats without discarding native format tests."""

        result = self.export(format, **parameters)
        if format == "json":
            fields = (
                json.loads(parameters["columns"]) if "columns" in parameters
                else [column.field for column in DELIVERY_EXPORT_COLUMNS]
            )
            columns = {column.field: column for column in DELIVERY_EXPORT_COLUMNS}
            return [[columns[field].label for field in fields]] + [
                [row[field] for field in fields] for row in result
            ]
        if format == "xml":
            return [[column.attrib["label"] for column in result.find("columns")]] + [
                [cell.text for cell in row] for row in result.find("rows")
            ]
        return result

    def test_all_formats_default_to_complete_public_schema(self):
        delivery = self.delivery("owned.zip", product_unit_code="CZ", submitted_product_unit_code="CZ01")
        self.delivery("another-owner.zip", user=self.other)
        fields = [column.field for column in DELIVERY_EXPORT_COLUMNS]
        labels = [column.label for column in DELIVERY_EXPORT_COLUMNS]
        for field in ("size_bytes", "id", "product_unit_code", "review_notes", "review_actor_username"):
            self.assertIn(field, fields)
        for field in ("actions", "can_delete", "action_owner_id", "submission_url", "s3_id"):
            self.assertNotIn(field, fields)

        for format in EXPORT_FORMATS:
            with self.subTest(format=format):
                rows = self.table_rows(format, delivery_view="all")
                self.assertEqual(rows[0], labels)
                self.assertEqual(len(rows), 2)
                self.assertEqual(len(rows[1]), len(fields))
                record = dict(zip(fields, rows[1]))
                self.assertEqual(record["filename"], delivery.filename)
                self.assertEqual(str(record["id"]), str(delivery.pk))
                self.assertEqual(str(record["size_bytes"]), "1024")
                self.assertEqual(record["product_unit_code"], "CZ")
                self.assertEqual(record["submitted_product_unit_code"], "CZ01")

    def test_complete_exports_keep_review_feedback_access_scope(self):
        product = Product.objects.create(ident="test", name="Test product")
        release = ProductRelease.objects.create(
            product=product, release_key="export-v1", revision=1,
            catalog_digest="a" * 64, is_current=True,
        )
        aoi = ProductUnit.objects.create(product_release=release, product_unit_code="CZ", provenance="manifest")
        delivery = self.delivery("reviewed.zip", date_submitted=timezone.now())
        job = Job.objects.create(
            delivery=delivery, product_ident=product.ident,
            product_release=release, job_status=JOB_OK,
        )
        submission = DeliverySubmission.objects.create(
            delivery=delivery, job=job, product_release=release, product_unit=aoi,
            product_unit_code="CZ", submitted_product_unit_code="CZ", submitted_by=self.user,
            submitted_by_username=self.user.username, request_channel="browser",
            publication_state="published", review_state="rejected", review_version=1,
            published_at=timezone.now(), artifact_path="/published/reviewed.zip",
            artifact_digest="b" * 64, input_digest="c" * 64,
        )
        SubmissionReviewEvent.objects.create(
            submission=submission, version=1, decision="declined",
            actor=self.other, actor_username=self.other.username, notes="Correct the geometry.",
        )
        # Region access permits the delivery row, but not its review correspondence.
        UserProfile.objects.create(user=self.user, country="CZ")
        UserRegionGrant.objects.create(user=self.other, region_code="CZ")
        self.other.user_permissions.add(Permission.objects.get(
            content_type__app_label="accounts", codename="view_region_deliveries",
        ))
        fields = [column.field for column in DELIVERY_EXPORT_COLUMNS]
        for viewer in (self.user, self.other):
            self.client.force_login(viewer)
            for format in EXPORT_FORMATS:
                with self.subTest(viewer=viewer.username, format=format):
                    rows = self.table_rows(format, delivery_view="all")
                    self.assertEqual(len(rows), 2)
                    record = dict(zip(fields, rows[1]))
                    self.assertEqual(record["filename"], delivery.filename)
                    if viewer == self.user:
                        self.assertEqual(record["review_notes"], "Correct the geometry.")
                        self.assertEqual(record["review_actor_username"], self.other.username)
                        self.assertEqual(record["submission_id"], str(submission.pk))
                    else:
                        for field in (
                            "submission_id", "submission_review_state", "review_notes",
                            "review_actor_username", "review_created_at",
                        ):
                            self.assertIn(record[field], (None, ""))

    def test_all_formats_include_every_matching_row_in_selected_column_order(self):
        # More than one server query batch as well as more than one UI page.
        Delivery.objects.bulk_create([
            Delivery(user=self.user, filename=f"batch-{index:04}.zip", size_bytes=index)
            for index in range(1003)
        ])
        self.delivery("batch-hidden.zip", user=self.other)
        self.delivery("unmatched.zip")
        expected = [["ID", "Delivery"]] + [list(row) for row in (
            Delivery.objects.filter(user=self.user, filename__startswith="batch-")
            .order_by("filename").values_list("id", "filename")
        )]
        for format in EXPORT_FORMATS:
            with self.subTest(format=format):
                rows = self.table_rows(
                    format, columns=json.dumps(["id", "filename"]),
                    delivery_view="all", search="batch-", sort="filename", order="asc",
                    offset=20, limit=2,
                )
                self.assertEqual(rows[0], expected[0])
                self.assertEqual([[str(cell) for cell in row] for row in rows[1:]],
                                 [[str(cell) for cell in row] for row in expected[1:]])

    def test_workflow_filter_and_group_order_match_json(self):
        self.delivery("a-pass.zip", status=JOB_OK)
        self.delivery("b-unvalidated.zip")
        self.delivery("z-failure.zip", status=JOB_FAILED)
        self.delivery("c-failure.zip", status=JOB_FAILED)
        self.delivery("running.zip", status=JOB_RUNNING)
        self.delivery("outside.zip", user=self.other, status=JOB_FAILED)
        parameters = {"delivery_view": "action_required", "sort": "filename", "order": "asc"}
        expected = self.client.get(reverse("deliveries_json"), parameters).json()["rows"]
        for format in EXPORT_FORMATS:
            with self.subTest(format=format):
                rows = self.table_rows(format, columns=json.dumps(["filename", "last_job_status"]), **parameters)
                self.assertEqual([row[0] for row in rows[1:]], [row["filename"] for row in expected])
                self.assertEqual([row[1] for row in rows[1:]], ["Failed", "Failed", "Not validated", "Validated"])
                passed = self.table_rows(format, columns='["filename"]', delivery_status="passed", **parameters)
                self.assertEqual(passed, [["Delivery"], ["a-pass.zip"]])

    def test_csv_quotes_unicode_newlines_and_formula_like_filenames(self):
        names = ['Český, "region"\n2026.zip', '=HYPERLINK("https://example.invalid")', " +SUM(1,2)"]
        for name in names:
            self.delivery(name)
        rows = self.export(columns='["filename"]', delivery_view="all", sort="id", order="asc")
        self.assertEqual(rows, [["Delivery"], [names[0]], ["'" + names[1]], ["'" + names[2]]])

    def test_empty_exports_keep_declared_headers(self):
        for format in EXPORT_FORMATS:
            with self.subTest(format=format):
                self.assertEqual(self.table_rows(format, columns='["filename","size_bytes"]'),
                                 [["Delivery", "Size (bytes)"]])

    def test_json_and_xml_keep_literal_values_and_native_types(self):
        delivery = self.delivery('=HYPERLINK("a<&b")')
        parameters = {"columns": '["filename","size_bytes","submission_id"]', "delivery_view": "all"}
        self.assertEqual(self.export("json", **parameters), [{
            "filename": delivery.filename, "size_bytes": 1024, "submission_id": None,
        }])
        cells = self.export("xml", **parameters).findall("rows/row/cell")
        self.assertEqual([(cell.attrib["field"], cell.attrib["type"], cell.text) for cell in cells], [
            ("filename", "string", delivery.filename), ("size_bytes", "number", "1024"),
            ("submission_id", "null", None),
        ])

    def test_invalid_format_or_columns_fail_before_querying_rows(self):
        invalid = [
            {"format": "pdf"}, {"format": ""}, {"columns": "not-json"},
            {"columns": "[]"}, {"columns": '{}'}, {"columns": '[null]'},
            {"columns": '["filename","filename"]'}, {"columns": '["actions"]'},
            {"columns": '["can_delete"]'}, {"columns": '["action_owner_id"]'},
            {"columns": '["submission_url"]'}, {"columns": '["s3_id"]'},
        ]
        with patch("qc_tool.frontend.dashboard.views.deliveries.listing.excel.iter_deliveries") as query:
            for parameters in invalid:
                with self.subTest(parameters=parameters):
                    self.assertEqual(self.client.get(self.url, parameters).status_code, 400)
            query.assert_not_called()

    def test_default_xlsx_schema_is_explicit_and_requires_login(self):
        self.delivery("owned.zip")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("deliveries.xlsx", response["Content-Disposition"])
        workbook = openpyxl.load_workbook(io.BytesIO(b"".join(response.streaming_content)), read_only=True)
        try:
            self.assertEqual(next(workbook.active.values), tuple(column.label for column in DELIVERY_EXPORT_COLUMNS))
        finally:
            workbook.close()
        self.client.logout()
        for format in EXPORT_FORMATS:
            self.assertNotEqual(self.client.get(self.url, {"format": format}).status_code, 200)
