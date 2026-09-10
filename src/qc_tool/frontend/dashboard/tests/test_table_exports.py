"""Application table conversion has one format contract and no data lookup."""

import csv
import io
import json
from unittest.mock import patch
from xml.etree import ElementTree

import openpyxl
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.templatetags.static import static
from django.urls import reverse


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class BrowserTableExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="table-export-user")

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("table_export")
        self.payload = {
            "format": "json", "filename": "products",
            "columns": [{"field": "name", "label": "Product"}, {"field": "count", "label": "Expected AOIs"}],
            "rows": [{"name": "Český <product> & region", "count": 42}, {"name": "=1+1", "count": None}],
        }

    def post(self, **changes):
        return self.client.post(self.url, {**self.payload, **changes}, content_type="application/json")

    def test_every_format_uses_the_same_projection_with_real_file_contents(self):
        for format in ("json", "csv", "xlsx", "xml"):
            with self.subTest(format=format):
                response = self.post(format=format, filename=f"products.{format}")
                self.assertEqual(response.status_code, 200)
                self.assertIn(f'filename="products.{format}"', response["Content-Disposition"])
                self.assertIn("no-store", response["Cache-Control"])
                content = b"".join(response.streaming_content)
                if format == "json":
                    self.assertEqual(json.loads(content), self.payload["rows"])
                elif format == "csv":
                    rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
                    self.assertEqual(rows, [["Product", "Expected AOIs"], [self.payload["rows"][0]["name"], "42"], ["'=1+1", ""]])
                elif format == "xlsx":
                    workbook = openpyxl.load_workbook(io.BytesIO(content))
                    try:
                        self.assertEqual(list(workbook.active.values), [("Product", "Expected AOIs"),
                            (self.payload["rows"][0]["name"], 42), ("'=1+1", None)])
                        self.assertNotEqual(workbook.active["A3"].data_type, "f")
                    finally:
                        workbook.close()
                else:
                    root = ElementTree.fromstring(content)
                    self.assertEqual([c.attrib for c in root.find("columns")], self.payload["columns"])
                    rows = root.findall("rows/row")
                    self.assertEqual(rows[0][0].text, self.payload["rows"][0]["name"])
                    self.assertEqual(rows[0][1].attrib["type"], "number")
                    self.assertEqual(rows[1][0].text, "=1+1")
                    self.assertEqual(rows[1][1].attrib["type"], "null")

    def test_filename_is_safe_and_unicode_downloads_are_supported(self):
        response = self.post(filename="České produkty.json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("filename*=utf-8''", response["Content-Disposition"])
        list(response.streaming_content)
        for filename in ("../secret", "data/file", "bad\r\nheader", "", "a" * 121):
            with self.subTest(filename=filename):
                self.assertEqual(self.post(filename=filename).status_code, 400)

    def test_invalid_snapshots_do_not_reach_a_serializer(self):
        invalid = [
            {"format": "pdf"}, {"format": None}, {"format": {}},
            {"columns": []}, {"columns": [{"field": "id"}]},
            {"columns": [{"field": "id", "label": "ID"}] * 2},
            {"rows": [{"undeclared": "private"}]}, {"rows": ["not a record"]},
            {"rows": [{"name": float("inf")}]}, {"rows": [{"count": float("nan")}]},
            {"rows": [{"name": "x" * 32768}]}, {"rows": [{"name": "\ud800"}]},
            {"rows": [{"name": "=" + "x" * 32766}]},
            {"source_url": "http://internal.invalid"}, {"table": "auth_user"},
        ]
        with patch("qc_tool.frontend.dashboard.views.table_exports.table_export_response") as serializer:
            for changes in invalid:
                with self.subTest(changes=list(changes)):
                    response = self.post(**changes)
                    self.assertEqual(response.status_code, 400)
                    self.assertIn("error", response.json())
            serializer.assert_not_called()

    def test_body_and_table_limits_fail_explicitly_without_truncation(self):
        with patch("qc_tool.frontend.dashboard.views.table_exports.MAX_EXPORT_BYTES", 20):
            self.assertEqual(self.post().status_code, 413)
        for limit in ("MAX_EXPORT_ROWS", "MAX_EXPORT_CELLS", "MAX_EXPORT_COLUMNS"):
            with patch("qc_tool.frontend.dashboard.services.exports.browser." + limit, 1):
                self.assertEqual(self.post().status_code, 400)
        self.assertEqual(self.client.post(self.url, data="{oops", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post(self.url, data="[]", content_type="text/plain").status_code, 415)

    def test_json_body_has_an_endpoint_limit_independent_of_form_upload_limits(self):
        with override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=32):
            response = self.post()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(json.loads(b"".join(response.streaming_content)), self.payload["rows"])

    def test_requires_session_post_permission_and_csrf(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.client.logout()
        self.assertEqual(self.post().status_code, 401)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url, self.payload, content_type="application/json").status_code, 403)
        client.get(reverse("deliveries"))
        token = client.cookies["csrftoken"].value
        response = client.post(self.url, self.payload, content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200)
        list(response.streaming_content)

    def test_workspace_configuration_has_the_same_ordered_formats(self):
        import re
        configs = []
        for page in ("deliveries", "products", "boundaries"):
            response = self.client.get(reverse(page))
            self.assertEqual(response.status_code, 200)
            match = re.search(r'<script id="qc-table-export-config" type="application/json">(.*?)</script>', response.content.decode())
            self.assertIsNotNone(match)
            configs.append(json.loads(match[1]))
        self.assertTrue(all(config == configs[0] for config in configs))
        self.assertEqual(configs[0], {
            "url": self.url,
            "iconSprite": static("dashboard/icons/ui.svg"),
            "formats": [
                {"value": value, "label": value.upper()} for value in ("json", "csv", "xlsx", "xml")
            ],
        })
