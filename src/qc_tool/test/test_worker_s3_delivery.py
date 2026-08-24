from io import BytesIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from unittest.mock import patch
from zipfile import ZIP_STORED
from zipfile import ZipFile

from qc_tool.worker.s3_delivery import download_s3_delivery
from qc_tool.worker.s3_delivery import S3DownloadError
from qc_tool.worker.s3_delivery import S3DownloadPolicy
from qc_tool.worker.s3_delivery.service import do_s3_download


ENDPOINT = "https://objects.example.com"


class FakeBody:
    def __init__(self, payload):
        self.stream = BytesIO(payload)
        self.closed = False

    def read(self, size):
        return self.stream.read(size)

    def close(self):
        self.closed = True


class FakeClient:
    def __init__(self, listing, payloads):
        self.listing = listing
        self.payloads = payloads
        self.list_calls = []
        self.get_calls = []
        self.meta = SimpleNamespace(
            events=SimpleNamespace(register=Mock()),
        )

    def list_objects_v2(self, **kwargs):
        self.list_calls.append(kwargs)
        return self.listing

    def get_object(self, **kwargs):
        self.get_calls.append(kwargs)
        payload = self.payloads[kwargs["Key"]]
        return {
            "ContentLength": len(payload),
            "Body": FakeBody(payload),
        }


class S3WorkerDownloadTests(TestCase):
    def setUp(self):
        self.policy = S3DownloadPolicy(
            allowed_endpoints=(ENDPOINT,),
            max_objects=10,
            max_download_bytes=1024 * 1024,
        )
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def download(self, client, destination=None, **overrides):
        factory = Mock(return_value=client)
        arguments = {
            "host": ENDPOINT,
            "access_key": "access-key",
            "secret_key": "secret-key",
            "bucket_name": "deliveries",
            "key_prefix": "incoming/product",
            "destination": destination or self.root.joinpath("download"),
            "policy": self.policy,
            "client_factory": factory,
        }
        arguments.update(overrides)
        return download_s3_delivery(**arguments), factory

    def test_policy_rejects_boolean_or_non_numeric_resource_limits(self):
        invalid_overrides = (
            {"max_objects": True},
            {"max_download_bytes": False},
            {"connect_timeout": "3"},
        )
        for overrides in invalid_overrides:
            values = {
                "allowed_endpoints": (ENDPOINT,),
                "max_objects": 10,
                "max_download_bytes": 1024,
            }
            values.update(overrides)
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    S3DownloadPolicy(**values)

    def test_downloads_one_bounded_sidecar_set_with_a_pinned_origin(self):
        listing = {
            "IsTruncated": False,
            "Contents": [
                {"Key": "incoming/product.shp", "Size": 3, "ETag": '"one"'},
                {"Key": "incoming/product.dbf", "Size": 4, "ETag": '"two"'},
            ],
        }
        client = FakeClient(
            listing,
            {
                "incoming/product.shp": b"shp",
                "incoming/product.dbf": b"data",
            },
        )

        result, factory = self.download(client)

        self.assertEqual(result.hash_files, ("product.shp", "product.dbf"))
        self.assertEqual(result.processing_dir, self.root.joinpath("download"))
        self.assertEqual(
            self.root.joinpath("download", "product.shp").read_bytes(),
            b"shp",
        )
        self.assertEqual(
            client.list_calls,
            [{"Bucket": "deliveries", "Prefix": "incoming/product", "MaxKeys": 10}],
        )
        self.assertEqual(client.get_calls[0]["IfMatch"], '"one"')
        config = factory.call_args.kwargs["config"]
        self.assertEqual(config.proxies, {})
        self.assertEqual(config.s3["addressing_style"], "path")

        event_name, guard = client.meta.events.register.call_args.args
        self.assertEqual(event_name, "before-send.s3")
        guard(SimpleNamespace(url=ENDPOINT + "/deliveries/product.shp"))
        with self.assertRaises(S3DownloadError):
            guard(SimpleNamespace(url="https://169.254.169.254/latest/meta-data"))

    def test_extracts_a_single_zip_with_the_shared_safe_extractor(self):
        archive = BytesIO()
        with ZipFile(archive, "w", compression=ZIP_STORED) as zip_file:
            zip_file.writestr("product/data.txt", "safe")
        payload = archive.getvalue()
        client = FakeClient(
            {
                "Contents": [
                    {"Key": "incoming/product.zip", "Size": len(payload)},
                ]
            },
            {"incoming/product.zip": payload},
        )

        result, _factory = self.download(client)

        self.assertEqual(result.hash_files, ("product.zip",))
        self.assertFalse(self.root.joinpath("download", "product.zip").exists())
        self.assertEqual(
            result.processing_dir.joinpath("product", "data.txt").read_text(),
            "safe",
        )

    def test_rejects_unlisted_endpoints_before_constructing_a_client(self):
        client = FakeClient({}, {})
        factory = Mock(return_value=client)

        with self.assertRaises(S3DownloadError):
            download_s3_delivery(
                "https://unlisted.example.com",
                "access-key",
                "secret-key",
                "deliveries",
                "incoming/product",
                self.root.joinpath("download"),
                policy=self.policy,
                client_factory=factory,
            )

        factory.assert_not_called()

    def test_rejects_truncated_ambiguous_and_colliding_listings(self):
        invalid_listings = (
            {
                "IsTruncated": True,
                "Contents": [{"Key": "incoming/product.zip", "Size": 1}],
            },
            {
                "Contents": [
                    {"Key": "incoming/one.shp", "Size": 1},
                    {"Key": "incoming/two.dbf", "Size": 1},
                ]
            },
            {
                "Contents": [
                    {"Key": "incoming/product.SHP", "Size": 1},
                    {"Key": "incoming/product.shp", "Size": 1},
                ]
            },
            {
                "Contents": [
                    {"Key": "incoming/product.zip", "Size": 1},
                    {"Key": "incoming/product.txt", "Size": 1},
                ]
            },
        )

        for index, listing in enumerate(invalid_listings):
            with self.subTest(index=index):
                destination = self.root.joinpath("invalid-{:d}".format(index))
                with self.assertRaises(S3DownloadError):
                    self.download(FakeClient(listing, {}), destination=destination)
                self.assertEqual(
                    list(destination.iterdir()) if destination.exists() else [],
                    [],
                )

    def test_stops_a_body_that_exceeds_its_declared_size_and_cleans_up(self):
        client = FakeClient(
            {"Contents": [{"Key": "incoming/product.shp", "Size": 3}]},
            {"incoming/product.shp": b"four"},
        )
        destination = self.root.joinpath("oversized")

        with self.assertRaises(S3DownloadError):
            self.download(client, destination=destination)

        self.assertEqual(list(destination.iterdir()), [])

    def test_environment_policy_is_disabled_by_default_and_strictly_bounded(self):
        variables = {
            "S3_ALLOWED_ENDPOINTS": "",
            "S3_MAX_LISTED_OBJECTS": "1001",
        }
        with patch.dict(os.environ, variables, clear=False):
            with self.assertRaises(S3DownloadError):
                S3DownloadPolicy.from_environment()

        with patch.dict(
            os.environ,
            {
                "S3_ALLOWED_ENDPOINTS": ENDPOINT,
                "S3_MAX_LISTED_OBJECTS": "10",
                "S3_MAX_DOWNLOAD_BYTES": "2048",
            },
            clear=False,
        ):
            policy = S3DownloadPolicy.from_environment()
        self.assertEqual(policy.allowed_endpoints, (ENDPOINT,))
        self.assertEqual(policy.max_objects, 10)
        self.assertEqual(policy.max_download_bytes, 2048)

    def test_legacy_status_adapter_never_exposes_internal_failures(self):
        status = SimpleNamespace(
            messages=[],
            params={},
            aborted=lambda message: status.messages.append(message),
        )
        secret_failure = RuntimeError("secret-key https://169.254.169.254")

        with patch(
            "qc_tool.worker.s3_delivery.service.download_s3_delivery",
            side_effect=secret_failure,
        ):
            with self.assertLogs(
                "qc_tool.worker.s3_delivery.service",
                level="WARNING",
            ) as logs:
                do_s3_download(
                    ENDPOINT,
                    "access-key",
                    "secret-key",
                    "deliveries",
                    "incoming/product",
                    self.root.joinpath("adapter"),
                    status,
                )

        output = " ".join(status.messages + logs.output)
        self.assertNotIn("secret-key", output)
        self.assertNotIn("169.254.169.254", output)


if __name__ == "__main__":
    import unittest

    unittest.main()
