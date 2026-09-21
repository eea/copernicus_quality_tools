"""Private, atomic credential files addressed by opaque database references.

The frontend owns this directory. A database backup contains no S3 secrets;
restore the private credential directory separately when restoring a deployment.
Credentials are bound to a source location and are never shared by deduplication.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import stat
from uuid import uuid4

from django.conf import settings


_REFERENCE = re.compile(r"[0-9a-f]{32}\Z")
_MAX_BYTES = 8192


class S3CredentialsUnavailable(Exception):
    def __init__(self):
        super().__init__("S3 credentials are unavailable. Register the delivery again or restore its credential store.")


@dataclass(frozen=True)
class S3Credentials:
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)


@contextmanager
def _directory(*, create=False):
    """Use a held directory descriptor so paths cannot switch after validation."""
    descriptor = None
    try:
        path = Path(settings.S3_CREDENTIALS_DIR)
        if create:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        metadata = os.fstat(descriptor)
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise S3CredentialsUnavailable()
        yield descriptor
    except (OSError, ValueError, TypeError):
        raise S3CredentialsUnavailable() from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _filename(reference):
    if not isinstance(reference, str) or not _REFERENCE.fullmatch(reference):
        raise S3CredentialsUnavailable()
    return reference + ".json"


def _credentials(payload):
    values = [payload.get("access_key"), payload.get("secret_key")]
    if any(
        not isinstance(value, str) or not 0 < len(value) <= 100
        or not value.isascii() or not value.isprintable() or value != value.strip()
        for value in values
    ):
        raise S3CredentialsUnavailable()
    return S3Credentials(*values)


def store_s3_credentials(registration):
    """Persist a complete private file before returning its unguessable reference."""
    payload = {
        "host": registration.endpoint,
        "bucketname": registration.bucket_name,
        "key_prefix": registration.key_prefix,
        "access_key": registration.access_key,
        "secret_key": registration.secret_key,
    }
    _credentials(payload)
    encoded = json.dumps(payload, ensure_ascii=True).encode("ascii")
    if len(encoded) > _MAX_BYTES:
        raise S3CredentialsUnavailable()
    reference = uuid4().hex
    filename = _filename(reference)
    staging = "." + filename + ".tmp"
    with _directory(create=True) as directory:
        staged = False
        published = False
        try:
            descriptor = os.open(
                staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600, dir_fd=directory,
            )
            staged = True
            with os.fdopen(descriptor, "wb") as output:
                output.write(encoded)
                output.flush()
                os.fsync(output.fileno())
            # link() publishes without replacing any pre-existing secret.
            os.link(staging, filename, src_dir_fd=directory, dst_dir_fd=directory,
                    follow_symlinks=False)
            published = True
            os.unlink(staging, dir_fd=directory)
            staged = False
            # Persist both publication and staging removal before the DB can
            # reference this file (a leftover hard link is refused on read).
            os.fsync(directory)
        except Exception:
            if published:
                os.unlink(filename, dir_fd=directory)
            raise
        finally:
            if staged:
                os.unlink(staging, dir_fd=directory)
    return reference


def load_s3_credentials(source):
    """Fail closed for missing, altered, redirected or publicly readable files."""
    filename = _filename(source.credential_ref)
    with _directory() as directory:
        descriptor = os.open(
            filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory,
        )
        with os.fdopen(descriptor, "rb") as stored:
            metadata = os.fstat(stored.fileno())
            if (not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_uid != os.geteuid()
                    or stat.S_IMODE(metadata.st_mode) & 0o077
                    or metadata.st_nlink != 1 or metadata.st_size > _MAX_BYTES):
                raise S3CredentialsUnavailable()
            try:
                payload = json.loads(stored.read(_MAX_BYTES + 1))
            except (ValueError, UnicodeError):
                raise S3CredentialsUnavailable() from None
    if not isinstance(payload, dict) or set(payload) != {
        "host", "bucketname", "key_prefix", "access_key", "secret_key",
    }:
        raise S3CredentialsUnavailable()
    if (payload["host"], payload["bucketname"], payload["key_prefix"]) != (
        source.host, source.bucketname, source.key_prefix,
    ):
        raise S3CredentialsUnavailable()
    return _credentials(payload)


def discard_s3_credentials(reference):
    """Remove only the file created for a registration whose DB write failed."""
    filename = _filename(reference)
    with _directory() as directory:
        try:
            os.unlink(filename, dir_fd=directory)
            os.fsync(directory)
        except FileNotFoundError:
            pass
