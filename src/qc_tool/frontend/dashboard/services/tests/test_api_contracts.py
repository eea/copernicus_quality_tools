import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from django.test import RequestFactory
from django.test import SimpleTestCase
from django.http import QueryDict

from qc_tool.frontend.dashboard.services.api import JsonRequestError
from qc_tool.frontend.dashboard.services.api import read_json_object
from qc_tool.frontend.dashboard.services.jobs import JobRequestError
from qc_tool.frontend.dashboard.services.jobs import parse_batch_job_creation_request
from qc_tool.frontend.dashboard.services.jobs import parse_job_creation_request
from qc_tool.frontend.dashboard.services.jobs import serialize_job_history


class JsonRequestTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def request(self, body):
        return self.factory.post(
            "/api/test",
            data=body,
            content_type="application/json",
        )

    def test_accepts_one_bounded_json_object(self):
        request = self.request(b'{"delivery_id": 1}')

        self.assertEqual(
            read_json_object(request, maximum_bytes=1024),
            {"delivery_id": 1},
        )

    def test_rejects_duplicates_non_finite_values_and_non_objects(self):
        bodies = (
            b'{"id": 1, "id": 2}',
            b'{"value": NaN}',
            b"[]",
        )

        for body in bodies:
            with self.subTest(body=body):
                with self.assertRaises(JsonRequestError):
                    read_json_object(self.request(body), maximum_bytes=1024)

    def test_rejects_a_body_over_the_endpoint_limit(self):
        with self.assertRaises(JsonRequestError) as raised:
            read_json_object(self.request(b"{}"), maximum_bytes=1)

        self.assertEqual(raised.exception.status_code, 413)
        self.assertEqual(raised.exception.code, "request_body_too_large")


class JobRequestTests(SimpleTestCase):
    def test_normalizes_one_valid_request_against_the_definition(self):
        with TemporaryDirectory() as directory:
            definition = Path(directory).joinpath("Product.json")
            definition.write_text(
                json.dumps(
                    {
                        "steps": [
                            {"required": False},
                            {"required": False},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with patch(
                "qc_tool.frontend.dashboard.services.jobs.requests.locate_product_definition",
                return_value=definition,
            ):
                result = parse_job_creation_request(
                    {
                        "delivery_id": "7",
                        "product_ident": "Product",
                        "skip_steps": "2",
                    }
                )

        self.assertEqual(result.delivery_id, 7)
        self.assertEqual(result.product_ident, "product")
        self.assertEqual(result.skip_steps, "2")

    def test_rejects_invalid_identifiers_and_skip_step_syntax(self):
        with TemporaryDirectory() as directory:
            definition = Path(directory).joinpath("product.json")
            definition.write_text('{"steps": []}', encoding="utf-8")
            with patch(
                "qc_tool.frontend.dashboard.services.jobs.requests.locate_product_definition",
                return_value=definition,
            ):
                payloads = (
                    {"delivery_id": True, "product_ident": "product"},
                    {"delivery_id": "01", "product_ident": "product"},
                    {
                        "delivery_id": 1,
                        "product_ident": "product",
                        "skip_steps": "1,__import__('os')",
                    },
                )
                for payload in payloads:
                    with self.subTest(payload=payload):
                        with self.assertRaises(JobRequestError):
                            parse_job_creation_request(payload)

    def test_validates_and_bounds_a_browser_job_batch_once(self):
        form = QueryDict(
            "delivery_ids=7%2C8&product_ident=Product&skip_steps=2"
        )
        with TemporaryDirectory() as directory:
            definition = Path(directory).joinpath("Product.json")
            definition.write_text(
                '{"steps":[{"required":false},{"required":false}]}',
                encoding="utf-8",
            )
            with patch(
                "qc_tool.frontend.dashboard.services.jobs.requests.locate_product_definition",
                return_value=definition,
            ):
                result = parse_batch_job_creation_request(form)

        self.assertEqual(result.delivery_ids, (7, 8))
        self.assertEqual(result.product_ident, "product")
        self.assertEqual(result.skip_steps, "2")

    def test_rejects_duplicate_fields_ids_and_oversized_batches(self):
        invalid_forms = (
            QueryDict("delivery_ids=1&delivery_ids=2&product_ident=p"),
            QueryDict("delivery_ids=1%2C1&product_ident=p"),
            QueryDict("delivery_ids=1%2C2&product_ident=p"),
        )
        limits = (100, 100, 1)
        for form, limit in zip(invalid_forms, limits):
            with self.subTest(form=form, limit=limit):
                with self.assertRaises(JobRequestError):
                    parse_batch_job_creation_request(
                        form,
                        maximum_deliveries=limit,
                    )


class JobSerializationTests(SimpleTestCase):
    def test_exposes_an_explicit_projection_without_worker_url(self):
        job = SimpleNamespace(
            job_uuid=UUID("00000000-0000-0000-0000-000000000001"),
            delivery_id=9,
            date_created=None,
            date_started=None,
            date_finished=None,
            job_status="ok",
            product_ident="product",
            product_description="Product",
            skip_steps=None,
            worker_url="http://worker.internal:8000/",
        )

        serialized = serialize_job_history([job])[0]

        self.assertNotIn("worker_url", serialized)
        self.assertEqual(
            serialized["job_uuid"],
            "00000000-0000-0000-0000-000000000001",
        )
