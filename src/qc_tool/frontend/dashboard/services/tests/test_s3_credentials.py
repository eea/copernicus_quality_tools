"""Credential storage has no database or network dependencies."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from qc_tool.frontend.dashboard.services.s3 import S3Registration
from qc_tool.frontend.dashboard.services.s3.credentials import (
    S3CredentialsUnavailable, discard_s3_credentials, load_s3_credentials,
    store_s3_credentials,
)


class S3CredentialStoreTests(SimpleTestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.store = self.root / "credentials"
        self.enterContext(override_settings(S3_CREDENTIALS_DIR=self.store))
        self.registration = S3Registration(
            endpoint="https://objects.example.test", access_key="test-access-key",
            secret_key="test-private-secret", bucket_name="deliveries", key_prefix="incoming/a.zip",
        )

    def source(self, reference):
        return SimpleNamespace(
            credential_ref=reference, host=self.registration.endpoint,
            bucketname=self.registration.bucket_name, key_prefix=self.registration.key_prefix,
        )

    def write(self):
        reference = store_s3_credentials(self.registration)
        return self.source(reference), self.store / (reference + ".json")

    def test_roundtrip_private_atomic_files_and_nonsecret_representations(self):
        source, path = self.write()
        credentials = load_s3_credentials(source)
        self.assertEqual(credentials.access_key, self.registration.access_key)
        self.assertEqual(credentials.secret_key, self.registration.secret_key)
        self.assertEqual(self.store.stat().st_mode & 0o777, 0o700)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.store.iterdir()), [path])
        for value in (repr(credentials), repr(self.registration)):
            self.assertNotIn(self.registration.secret_key, value)
            self.assertNotIn(self.registration.access_key, value)

    def test_independent_registrations_never_share_secret_references(self):
        first, first_path = self.write()
        second, _ = self.write()
        self.assertNotEqual(first.credential_ref, second.credential_ref)
        discard_s3_credentials(first.credential_ref)
        self.assertFalse(first_path.exists())
        self.assertEqual(load_s3_credentials(second).secret_key, self.registration.secret_key)
        discard_s3_credentials(first.credential_ref)

    def test_missing_invalid_and_traversal_references_fail_closed(self):
        for reference in (None, "", "../private-secret", "a" * 32, "A" * 32, "a" * 33):
            with self.subTest(reference=reference):
                with self.assertRaises(S3CredentialsUnavailable):
                    load_s3_credentials(self.source(reference))

    def test_secret_cannot_be_reused_at_another_location(self):
        for field in ("host", "bucketname", "key_prefix"):
            source, _ = self.write()
            setattr(source, field, "different")
            with self.subTest(field=field), self.assertRaises(S3CredentialsUnavailable):
                load_s3_credentials(source)

    def test_refuses_insecure_or_symlink_directory_without_modifying_it(self):
        actual = self.root / "other"
        actual.mkdir(mode=0o700)
        self.store.symlink_to(actual, target_is_directory=True)
        with self.assertRaises(S3CredentialsUnavailable):
            store_s3_credentials(self.registration)
        self.assertEqual(list(actual.iterdir()), [])
        self.store.unlink()
        self.store.mkdir(mode=0o755)
        self.store.chmod(0o755)
        with self.assertRaises(S3CredentialsUnavailable):
            store_s3_credentials(self.registration)
        self.assertEqual(self.store.stat().st_mode & 0o777, 0o755)

    def test_rejects_symlink_directory_when_loading(self):
        source, _ = self.write()
        actual = self.root / "moved"
        self.store.rename(actual)
        self.store.symlink_to(actual, target_is_directory=True)
        with self.assertRaises(S3CredentialsUnavailable):
            load_s3_credentials(source)

    def test_rejects_symlink_hardlink_and_public_secret_files(self):
        source, path = self.write()
        path.chmod(0o644)
        with self.assertRaises(S3CredentialsUnavailable):
            load_s3_credentials(source)
        path.chmod(0o600)
        alias = self.store / "alias"
        alias.hardlink_to(path)
        with self.assertRaises(S3CredentialsUnavailable):
            load_s3_credentials(source)
        alias.unlink()
        original = self.root / "original"
        path.rename(original)
        path.symlink_to(original)
        with self.assertRaises(S3CredentialsUnavailable):
            load_s3_credentials(source)

    def test_rejects_corrupted_oversized_and_invalid_content_without_echoing_it(self):
        source, path = self.write()
        original = json.loads(path.read_bytes())
        payloads = [b"invalid test-private-secret", b"x" * 8193, b"null"]
        payloads.append(json.dumps({**original, "secret_key": None}).encode())
        payloads.append(json.dumps({**original, "unexpected": "value"}).encode())
        for payload in payloads:
            path.write_bytes(payload)
            with self.assertRaises(S3CredentialsUnavailable) as failure:
                load_s3_credentials(source)
            self.assertNotIn(self.registration.secret_key, str(failure.exception))

    @patch("qc_tool.frontend.dashboard.services.s3.credentials.os.link", side_effect=OSError("synthetic"))
    def test_failed_publication_removes_partial_file(self, publish):
        with self.assertRaises(S3CredentialsUnavailable):
            store_s3_credentials(self.registration)
        self.assertEqual(list(self.store.iterdir()), [])

    def test_sync_failure_removes_staged_and_published_files(self):
        for failures in ([OSError("write sync failed")], [None, OSError("directory sync failed")]):
            with patch("qc_tool.frontend.dashboard.services.s3.credentials.os.fsync", side_effect=failures):
                with self.assertRaises(S3CredentialsUnavailable):
                    store_s3_credentials(self.registration)
            self.assertEqual(list(self.store.iterdir()), [])

    def test_reference_collision_never_changes_an_existing_file(self):
        source, path = self.write()
        original = path.read_bytes()
        with patch("qc_tool.frontend.dashboard.services.s3.credentials.uuid4",
                   return_value=SimpleNamespace(hex=source.credential_ref)):
            with self.assertRaises(S3CredentialsUnavailable):
                store_s3_credentials(self.registration)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(self.store.iterdir()), [path])

    def test_staging_collision_does_not_delete_an_existing_file(self):
        self.store.mkdir(mode=0o700)
        reference = "a" * 32
        existing = self.store / ("." + reference + ".json.tmp")
        existing.write_bytes(b"previous attempt")
        with patch("qc_tool.frontend.dashboard.services.s3.credentials.uuid4",
                   return_value=SimpleNamespace(hex=reference)):
            with self.assertRaises(S3CredentialsUnavailable):
                store_s3_credentials(self.registration)
        self.assertEqual(existing.read_bytes(), b"previous attempt")
