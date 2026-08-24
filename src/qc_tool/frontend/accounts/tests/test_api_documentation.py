from django.test import SimpleTestCase
from django.urls import reverse


class ApiDocumentationSecurityTests(SimpleTestCase):
    def test_public_documentation_uses_only_local_assets_and_never_collects_secrets(self):
        response = self.client.get(reverse("api_homepage"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Authorization: Bearer")
        self.assertContains(response, reverse("api_openapi_json"))
        self.assertNotContains(response, "unpkg.com")
        self.assertNotContains(response, "SwaggerUIBundle")
        self.assertNotContains(response, 'type="password"')

    def test_openapi_contract_declares_header_bearer_authentication(self):
        response = self.client.get(reverse("api_openapi_json"))

        self.assertEqual(response.status_code, 200)
        scheme = response.json()["components"]["securitySchemes"]["ApiKeyAuth"]
        self.assertEqual(scheme["type"], "http")
        self.assertEqual(scheme["scheme"], "bearer")
        self.assertNotIn("in", scheme)
        self.assertNotIn("name", scheme)
