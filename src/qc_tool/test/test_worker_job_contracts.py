import json
from unittest import TestCase

from qc_tool.worker.jobs import MAX_PULL_RESPONSE_BYTES
from qc_tool.worker.jobs import PulledJobError
from qc_tool.worker.jobs import read_pulled_job


class FakeResponse:
    def __init__(self, payload, headers=None):
        self.payload = payload
        self.headers = headers or {}
        self.read_size = None

    def read(self, size):
        self.read_size = size
        return self.payload[:size]


def valid_job(**updates):
    payload = {
        "job_uuid": "00000000-0000-0000-0000-000000000001",
        "product_ident": "clc2024",
        "username": "alice",
        "filename": "delivery.zip",
        "skip_steps": "1,2",
    }
    payload.update(updates)
    return payload


class PulledJobContractTests(TestCase):
    def test_accepts_only_an_explicit_local_or_complete_s3_contract(self):
        local = FakeResponse(json.dumps(valid_job()).encode("utf-8"))
        self.assertEqual(read_pulled_job(local)["username"], "alice")
        self.assertEqual(local.read_size, MAX_PULL_RESPONSE_BYTES + 1)

        s3_payload = valid_job(
            s3_host="https://objects.example.test",
            s3_access_key="access",
            s3_secret_key="secret",
            s3_bucketname="deliveries",
            s3_key_prefix="incoming/delivery",
        )
        s3 = read_pulled_job(
            FakeResponse(json.dumps(s3_payload).encode("utf-8"))
        )
        self.assertEqual(s3["s3_secret_key"], "secret")

    def test_accepts_null_as_an_empty_queue(self):
        self.assertIsNone(read_pulled_job(FakeResponse(b"null")))

    def test_rejects_oversized_duplicate_or_non_object_json(self):
        invalid_responses = (
            FakeResponse(
                b"{}",
                {"Content-Length": str(MAX_PULL_RESPONSE_BYTES + 1)},
            ),
            FakeResponse(b"{" + b"x" * MAX_PULL_RESPONSE_BYTES + b"}"),
            FakeResponse(b'{"job_uuid":"one","job_uuid":"two"}'),
            FakeResponse(b"[]"),
        )
        for response in invalid_responses:
            with self.subTest(payload=response.payload[:30]):
                with self.assertRaises(PulledJobError):
                    read_pulled_job(response)

    def test_rejects_paths_partial_s3_and_protocol_expansion(self):
        invalid_payloads = (
            valid_job(username="../alice"),
            valid_job(filename="nested/delivery.zip"),
            valid_job(product_ident="list"),
            valid_job(product_ident="product/child"),
            valid_job(s3_host="https://objects.example.test"),
            valid_job(unexpected="value"),
            valid_job(skip_steps="1,,2"),
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(PulledJobError):
                    read_pulled_job(
                        FakeResponse(json.dumps(payload).encode("utf-8"))
                    )
