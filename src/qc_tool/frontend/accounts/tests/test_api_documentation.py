import json
from unittest.mock import patch

from django.test import RequestFactory
from django.test import SimpleTestCase
from django.urls import reverse

from qc_tool.common import QCException
from qc_tool.frontend.dashboard.views import api_product_info


EXPECTED_OPERATIONS = {
    "/register-delivery": "post",
    "/register-delivery-s3": "post",
    "/delivery-list": "get",
    "/product-list": "get",
    "/product-info/{product_ident}": "get",
    "/create-job": "post",
    "/job-result/{job_uuid}": "get",
    "/job-result-pdf/{job_uuid}": "get",
    "/job-history/{delivery_id}": "get",
    "/submit-delivery-to-eea": "post",
}


class ApiDocumentationSecurityTests(SimpleTestCase):
    def test_documentation_is_anonymous_and_uses_only_bundled_assets(self):
        response = self.client.get(reverse("api_homepage"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Authorization: Bearer")
        self.assertContains(response, reverse("api_openapi_json"))
        self.assertContains(response, "dashboard/css/pages/api-docs.css")
        self.assertContains(response, "dashboard/js/api-docs.js")
        self.assertContains(response, 'id="api-operation-search"')
        self.assertContains(response, "data-api-expand")
        self.assertNotContains(response, "unpkg.com")
        self.assertNotContains(response, "cdn.jsdelivr.net")
        self.assertNotContains(response, "SwaggerUIBundle")
        self.assertNotContains(response, 'type="password"')

    def test_openapi_document_is_anonymous_and_declares_bearer_tokens(self):
        response = self.client.get(reverse("api_openapi_json"))

        self.assertEqual(response.status_code, 200)
        document = response.json()
        scheme = document["components"]["securitySchemes"][
            "PersonalAccessToken"
        ]
        self.assertEqual(
            set(document["components"]["securitySchemes"]),
            {"PersonalAccessToken"},
        )
        self.assertEqual(scheme["type"], "http")
        self.assertEqual(scheme["scheme"], "bearer")
        self.assertNotIn("in", scheme)
        self.assertNotIn("name", scheme)
        self.assertEqual(document["security"], [{"PersonalAccessToken": []}])

    def test_contract_documents_every_operational_query_in_detail(self):
        document = self.client.get(reverse("api_openapi_json")).json()

        self.assertEqual(set(document["paths"]), set(EXPECTED_OPERATIONS))
        operation_ids = set()
        for path, method in EXPECTED_OPERATIONS.items():
            with self.subTest(path=path, method=method):
                operation = document["paths"][path][method]
                self.assertTrue(operation["operationId"])
                self.assertNotIn(operation["operationId"], operation_ids)
                operation_ids.add(operation["operationId"])
                self.assertTrue(operation["summary"])
                self.assertGreater(len(operation["description"]), 40)
                self.assertTrue(operation["tags"])
                self.assertTrue(operation["x-required-permission-label"])
                self.assertIn("401", operation["responses"])
                self.assertIn("403", operation["responses"])

    def test_delivery_list_query_parameters_have_nested_constraints(self):
        document = self.client.get(reverse("api_openapi_json")).json()
        parameters = {
            parameter["name"]: parameter
            for parameter in document["paths"]["/delivery-list"]["get"][
                "parameters"
            ]
        }

        self.assertEqual(set(parameters), {"offset", "limit", "sort", "order"})
        for parameter in parameters.values():
            self.assertEqual(parameter["in"], "query")
            self.assertFalse(parameter["required"])
            self.assertTrue(parameter["description"])
            self.assertIn("schema", parameter)

        self.assertEqual(
            parameters["offset"]["schema"],
            {
                "type": "integer",
                "minimum": 0,
                "maximum": 10_000_000,
                "default": 0,
            },
        )
        self.assertEqual(
            parameters["limit"]["schema"],
            {
                "type": "integer",
                "minimum": 1,
                "maximum": 1_000,
                "default": 20,
            },
        )
        self.assertEqual(
            parameters["order"]["schema"],
            {
                "type": "string",
                "enum": ["asc", "desc"],
                "default": "desc",
            },
        )
        self.assertIn("id", parameters["sort"]["schema"]["enum"])
        self.assertIn(
            "date_uploaded",
            parameters["sort"]["schema"]["enum"],
        )

    def test_contract_explains_snapshot_intersection_security_model(self):
        document = self.client.get(reverse("api_openapi_json")).json()
        description = document["info"]["description"].casefold()
        scheme_description = document["components"]["securitySchemes"][
            "PersonalAccessToken"
        ]["description"].casefold()

        for text in (description, scheme_description):
            self.assertIn("intersection", text)
            self.assertIn("snapshot", text)
            self.assertIn("current", text)
            self.assertIn("later grants", text)

    @patch(
        "qc_tool.frontend.dashboard.views.compile_job_form_data",
        side_effect=QCException("internal definition path must stay private"),
    )
    def test_unavailable_product_uses_the_documented_generic_json_404(
        self,
        _compile_job_form_data,
    ):
        response = api_product_info(
            RequestFactory().get("/api/product-info/unavailable"),
            "unavailable",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            json.loads(response.content),
            {
                "status": "error",
                "code": "product_not_found",
                "message": "The requested product is unavailable.",
            },
        )
        self.assertNotIn(b"internal definition path", response.content)
