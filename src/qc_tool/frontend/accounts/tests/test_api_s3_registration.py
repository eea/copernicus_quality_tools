import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from qc_tool.frontend.accounts.services.api_tokens import (
    issue_personal_access_token,
)
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import S3Info
from qc_tool.frontend.dashboard.services.s3 import S3Delivery
from qc_tool.frontend.dashboard.services.s3 import S3RegistrationError


ALLOWED_ENDPOINT = "https://objects.example.com"


@override_settings(
    S3_ALLOWED_ENDPOINTS=(ALLOWED_ENDPOINT,),
    S3_CONNECT_TIMEOUT_SECONDS=2,
    S3_READ_TIMEOUT_SECONDS=8,
    S3_MAX_LISTED_OBJECTS=250,
)
class ApiS3RegistrationSecurityTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="s3-api-owner")
        self.raw_key = issue_personal_access_token(
            self.user,
            "S3 registration tests",
        ).raw_token
        self.authorization = "Bearer {:s}".format(self.raw_key)

    def payload(self, **overrides):
        payload = {
            "host": ALLOWED_ENDPOINT,
            "access_key": "access-key",
            "secret_key": "secret-key",
            "bucketname": "deliveries",
            "key_prefix": "incoming/product",
        }
        payload.update(overrides)
        return payload

    def post(self, payload, *, encode=True):
        data = json.dumps(payload) if encode else payload
        return self.client.post(
            reverse("api_register_delivery_s3"),
            data=data,
            content_type="application/json",
            HTTP_AUTHORIZATION=self.authorization,
        )

    @patch("qc_tool.frontend.dashboard.views.inspect_s3_delivery")
    def test_rejects_an_unlisted_endpoint_before_any_network_call(self, inspect):
        response = self.post(
            self.payload(host="https://attacker.example.com")
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "s3_endpoint_not_allowed")
        inspect.assert_not_called()
        self.assertFalse(Delivery.objects.exists())
        self.assertFalse(S3Info.objects.exists())

    @override_settings(S3_ALLOWED_ENDPOINTS=())
    @patch("qc_tool.frontend.dashboard.views.inspect_s3_delivery")
    def test_empty_allowlist_disables_the_endpoint(self, inspect):
        response = self.post(self.payload())

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "s3_configuration_error")
        inspect.assert_not_called()

    @patch("qc_tool.frontend.dashboard.views.find_product_description")
    @patch("qc_tool.frontend.dashboard.views.guess_product_ident")
    @patch("qc_tool.frontend.dashboard.views.inspect_s3_delivery")
    def test_registers_one_validated_bounded_lookup_atomically(
        self,
        inspect,
        guess_product_ident,
        find_product_description,
    ):
        inspect.return_value = S3Delivery(
            filename="incoming/product",
            size_bytes=42,
        )
        guess_product_ident.return_value = "product"
        find_product_description.return_value = "Product"

        response = self.post(
            self.payload(host="https://OBJECTS.EXAMPLE.COM:443/")
        )

        self.assertEqual(response.status_code, 200)
        registration = inspect.call_args.args[0]
        self.assertEqual(registration.endpoint, ALLOWED_ENDPOINT)
        self.assertEqual(
            inspect.call_args.kwargs,
            {
                "connect_timeout": 2,
                "read_timeout": 8,
                "maximum_objects": 250,
            },
        )
        delivery = Delivery.objects.get()
        self.assertEqual(delivery.user, self.user)
        self.assertEqual(delivery.filename, "product")
        self.assertEqual(delivery.size_bytes, 42)
        self.assertEqual(delivery.s3.host, ALLOWED_ENDPOINT)
        self.assertEqual(delivery.s3.bucketname, "deliveries")
        self.assertEqual(delivery.s3.key_prefix, "incoming/product")

    @patch("qc_tool.frontend.dashboard.views.inspect_s3_delivery")
    def test_returns_only_a_generic_upstream_error(self, inspect):
        inspect.side_effect = S3RegistrationError(
            "s3_lookup_failed",
            "The configured S3 service could not be queried.",
            status_code=502,
        )

        response = self.post(self.payload())

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], "s3_lookup_failed")
        self.assertNotContains(response, "secret-key", status_code=502)
        self.assertNotContains(response, ALLOWED_ENDPOINT, status_code=502)
        self.assertFalse(S3Info.objects.exists())

    @patch("qc_tool.frontend.dashboard.views.inspect_s3_delivery")
    def test_rejects_invalid_json_and_oversized_bodies_without_lookup(
        self,
        inspect,
    ):
        invalid_json = self.post("{", encode=False)
        oversized = self.post("x" * (16 * 1024 + 1), encode=False)

        self.assertEqual(invalid_json.status_code, 400)
        self.assertEqual(invalid_json.json()["code"], "invalid_json")
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(
            oversized.json()["code"],
            "request_body_too_large",
        )
        inspect.assert_not_called()
