from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from qc_tool.frontend.dashboard.services.s3 import S3Registration
from qc_tool.frontend.dashboard.services.s3 import S3RegistrationError
from qc_tool.frontend.dashboard.services.s3 import inspect_s3_delivery
from qc_tool.frontend.dashboard.services.s3 import parse_s3_registration


ALLOWED_ENDPOINT = "https://objects.example.com"


def registration_payload(**overrides):
    payload = {
        "host": ALLOWED_ENDPOINT,
        "access_key": "access-key",
        "secret_key": "secret-key",
        "bucketname": "deliveries",
        "key_prefix": "incoming/product",
    }
    payload.update(overrides)
    return payload


class S3EndpointValidationTests(SimpleTestCase):
    def parse(self, payload=None, allowed_endpoints=(ALLOWED_ENDPOINT,)):
        return parse_s3_registration(
            registration_payload() if payload is None else payload,
            allowed_endpoints=allowed_endpoints,
        )

    def test_allows_only_a_canonical_exact_https_origin(self):
        registration = self.parse(
            registration_payload(
                host="https://OBJECTS.EXAMPLE.COM:443/",
            )
        )

        self.assertEqual(registration.endpoint, ALLOWED_ENDPOINT)

    def test_empty_allowlist_disables_s3_registration(self):
        with self.assertRaises(S3RegistrationError) as raised:
            self.parse(allowed_endpoints=())

        self.assertEqual(raised.exception.code, "s3_configuration_error")
        self.assertEqual(raised.exception.status_code, 503)

    def test_invalid_allowlist_fails_closed(self):
        with self.assertRaises(S3RegistrationError) as raised:
            self.parse(
                allowed_endpoints=(ALLOWED_ENDPOINT, "http://unsafe.example.com"),
            )

        self.assertEqual(raised.exception.code, "s3_configuration_error")

    def test_rejects_unlisted_and_unsafe_endpoint_forms(self):
        unsafe_endpoints = (
            "https://other.example.com",
            "http://objects.example.com",
            "https://user:pass@objects.example.com",
            "https://objects.example.com/storage",
            "https://objects.example.com?target=elsewhere",
            "https://objects.example.com#fragment",
            "https://127.0.0.1",
            "https://169.254.169.254",
            "https://[::1]",
            "https://metadata.google.internal",
            "https://2130706433",
            "https://objects.example.com\\@169.254.169.254",
        )

        for endpoint in unsafe_endpoints:
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(S3RegistrationError) as raised:
                    self.parse(registration_payload(host=endpoint))
                self.assertEqual(
                    raised.exception.code,
                    "s3_endpoint_not_allowed",
                )

    def test_rejects_missing_oversized_and_non_string_fields(self):
        invalid_payloads = (
            registration_payload(secret_key=None),
            registration_payload(access_key="x" * 101),
            registration_payload(bucketname=["deliveries"]),
            registration_payload(key_prefix="line\nbreak"),
            [],
        )

        for payload in invalid_payloads:
            with self.subTest(payload_type=type(payload).__name__):
                with self.assertRaises(S3RegistrationError) as raised:
                    self.parse(payload)
                self.assertEqual(raised.exception.code, "invalid_s3_request")


class S3InspectionTests(SimpleTestCase):
    def setUp(self):
        self.registration = S3Registration(
            endpoint=ALLOWED_ENDPOINT,
            access_key="access-key",
            secret_key="secret-key",
            bucket_name="deliveries",
            key_prefix="incoming/product",
        )
        self.client = Mock()
        self.client_factory = Mock(return_value=self.client)

    def inspect(self, **overrides):
        arguments = {
            "connect_timeout": 2.5,
            "read_timeout": 7.5,
            "maximum_objects": 100,
            "client_factory": self.client_factory,
        }
        arguments.update(overrides)
        return inspect_s3_delivery(self.registration, **arguments)

    def test_uses_one_bounded_path_style_request_and_sums_sidecars(self):
        self.client.list_objects_v2.return_value = {
            "IsTruncated": False,
            "Contents": [
                {"Key": "incoming/product.shp", "Size": 11},
                {"Key": "incoming/product.dbf", "Size": 7},
            ],
        }

        delivery = self.inspect()

        self.assertEqual(delivery.filename, "incoming/product")
        self.assertEqual(delivery.size_bytes, 18)
        self.client.list_objects_v2.assert_called_once_with(
            Bucket="deliveries",
            Prefix="incoming/product",
            MaxKeys=100,
        )
        call = self.client_factory.call_args
        self.assertEqual(call.args, ("s3",))
        self.assertEqual(call.kwargs["endpoint_url"], ALLOWED_ENDPOINT)
        self.assertEqual(call.kwargs["region_name"], "us-east-1")
        config = call.kwargs["config"]
        self.assertEqual(config.connect_timeout, 2.5)
        self.assertEqual(config.read_timeout, 7.5)
        self.assertEqual(config.retries["total_max_attempts"], 2)
        self.assertEqual(config.s3["addressing_style"], "path")
        self.assertFalse(config.inject_host_prefix)
        event, endpoint_guard = self.client.meta.events.register.call_args.args
        self.assertEqual(event, "before-send.s3")
        endpoint_guard(
            SimpleNamespace(
                url="https://objects.example.com/deliveries?prefix=incoming",
            )
        )
        with self.assertRaises(RuntimeError):
            endpoint_guard(
                SimpleNamespace(
                    url="https://169.254.169.254/latest/meta-data",
                )
            )

    def test_rejects_a_truncated_listing(self):
        self.client.list_objects_v2.return_value = {
            "IsTruncated": True,
            "Contents": [{"Key": "incoming/product.zip", "Size": 1}],
        }

        with self.assertRaises(S3RegistrationError) as raised:
            self.inspect(maximum_objects=1)

        self.assertEqual(raised.exception.code, "s3_listing_limit_exceeded")

    def test_rejects_no_match_and_ambiguous_matches(self):
        responses = (
            ({"Contents": []}, "s3_delivery_not_found"),
            (
                {
                    "Contents": [
                        {"Key": "incoming/one.zip", "Size": 1},
                        {"Key": "incoming/two.zip", "Size": 2},
                    ]
                },
                "s3_delivery_ambiguous",
            ),
        )

        for response, expected_code in responses:
            with self.subTest(expected_code=expected_code):
                self.client.list_objects_v2.return_value = response
                with self.assertRaises(S3RegistrationError) as raised:
                    self.inspect()
                self.assertEqual(raised.exception.code, expected_code)

    def test_upstream_exception_is_replaced_by_a_generic_safe_error(self):
        self.client.list_objects_v2.side_effect = RuntimeError(
            "secret-key at http://169.254.169.254/internal"
        )

        with self.assertLogs(
            "qc_tool.frontend.dashboard.services.s3.inspection",
            level="WARNING",
        ) as captured:
            with self.assertRaises(S3RegistrationError) as raised:
                self.inspect()

        self.assertEqual(raised.exception.code, "s3_lookup_failed")
        self.assertEqual(raised.exception.status_code, 502)
        self.assertNotIn("secret-key", raised.exception.message)
        self.assertNotIn("169.254.169.254", raised.exception.message)
        self.assertNotIn("secret-key", " ".join(captured.output))
        self.assertNotIn("169.254.169.254", " ".join(captured.output))

    def test_invalid_bounds_fail_before_constructing_a_client(self):
        for overrides in (
            {"maximum_objects": 0},
            {"maximum_objects": 1001},
            {"connect_timeout": 0},
            {"read_timeout": float("inf")},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(S3RegistrationError) as raised:
                    self.inspect(**overrides)
                self.assertEqual(raised.exception.code, "s3_configuration_error")
        self.client_factory.assert_not_called()
