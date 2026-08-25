"""Tests for the OpenAPI-backed public documentation view models."""

from django.test import SimpleTestCase

from qc_tool.frontend.dashboard.services.api import ApiDocumentationError
from qc_tool.frontend.dashboard.services.api import api_documentation_context
from qc_tool.frontend.dashboard.services.api import openapi_document


class ApiDocumentationContractTests(SimpleTestCase):
    def test_runtime_server_url_is_normalized_without_mutating_source(self):
        first = openapi_document("https://qc.example.test/api/")
        first["info"]["title"] = "mutated"
        second = openapi_document("https://other.example.test/api")

        self.assertEqual(first["servers"][0]["url"], "https://qc.example.test/api")
        self.assertEqual(second["servers"][0]["url"], "https://other.example.test/api")
        self.assertEqual(second["info"]["title"], "CLMS QC Tool API")

    def test_runtime_server_url_rejects_unsafe_or_ambiguous_values(self):
        unsafe_values = (
            "javascript:alert(1)",
            "https://user:secret@qc.example.test/api",
            "https://qc.example.test/api?token=value",
            "https://qc.example.test/api#fragment",
            "https://[invalid/api",
            "https://qc.example.test:not-a-port/api",
        )

        for value in unsafe_values:
            with self.subTest(value=value):
                with self.assertRaises(ApiDocumentationError):
                    openapi_document(value)

    def test_every_operation_explains_permission_responses_and_behavior(self):
        document = openapi_document("https://qc.example.test/api")
        operations = [
            operation
            for path_item in document["paths"].values()
            for method, operation in path_item.items()
            if method in {"get", "post", "put", "patch", "delete"}
        ]

        self.assertEqual(len(operations), 10)
        for operation in operations:
            with self.subTest(operation=operation["operationId"]):
                self.assertTrue(operation["summary"])
                self.assertTrue(operation["description"])
                self.assertTrue(operation["x-required-permission-label"])
                self.assertIn("200", operation["responses"])
                self.assertIn("401", operation["responses"])
                self.assertIn("403", operation["responses"])

    def test_delivery_query_parameters_use_openapi_three_schema_objects(self):
        document = openapi_document("https://qc.example.test/api")
        parameters = document["paths"]["/delivery-list"]["get"]["parameters"]

        self.assertEqual(
            [parameter["name"] for parameter in parameters],
            ["offset", "limit", "sort", "order"],
        )
        for parameter in parameters:
            self.assertEqual(parameter["in"], "query")
            self.assertIsInstance(parameter["schema"], dict)
            self.assertNotIn("type", {key for key in parameter if key != "schema"})

    def test_human_context_resolves_parameters_and_uses_secret_placeholders(self):
        context = api_documentation_context("https://qc.example.test/api/")
        operations = {
            operation["path"]: operation
            for group in context["api_groups"]
            for operation in group["operations"]
        }

        self.assertEqual(context["api_operation_count"], 10)
        result_operation = operations["/job-result/{job_uuid}"]
        self.assertEqual(result_operation["parameters"][0]["name"], "job_uuid")
        self.assertNotIn("{job_uuid}", result_operation["curl_example"])
        self.assertIn(
            "?offset=0&limit=20&sort=date_uploaded&order=desc",
            operations["/delivery-list"]["curl_example"],
        )
        for operation in operations.values():
            self.assertIn(
                "Authorization: Bearer <personal-access-token>",
                operation["curl_example"],
            )

    def test_personal_access_token_contract_is_least_privilege(self):
        document = openapi_document("https://qc.example.test/api")
        scheme = document["components"]["securitySchemes"][
            "PersonalAccessToken"
        ]

        self.assertEqual(document["security"], [{"PersonalAccessToken": []}])
        self.assertEqual(scheme["type"], "http")
        self.assertEqual(scheme["scheme"], "bearer")
        self.assertIn("intersection", scheme["description"])
        self.assertIn("shown once", scheme["description"])
        self.assertIn("Delete tokens individually", scheme["description"])

    def test_every_local_openapi_reference_resolves(self):
        document = openapi_document("https://qc.example.test/api")

        for reference in _references_in(document):
            with self.subTest(reference=reference):
                self.assertTrue(reference.startswith("#/"))
                current = document
                for part in reference[2:].split("/"):
                    self.assertIsInstance(current, dict)
                    self.assertIn(part, current)
                    current = current[part]


def _references_in(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            if key == "$ref":
                yield nested
            else:
                yield from _references_in(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _references_in(nested)
