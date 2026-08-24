"""Orchestrate bounded, allowlisted materialization of one S3 delivery."""

import logging

import boto3

from qc_tool.archive_security import safely_extract_zip
from qc_tool.archive_security import UnsafeArchiveError

from .client import create_client
from .contracts import S3DownloadResult
from .errors import rejected_delivery
from .errors import S3DownloadError
from .errors import upstream_error
from .hashing import hash_file
from .hashing import hash_files
from .objects import validate_object_listing
from .policy import S3DownloadPolicy
from .storage import prepare_destination
from .storage import remove_created_files
from .transfer import download_object


logger = logging.getLogger(__name__)


def download_s3_delivery(
    host,
    access_key,
    secret_key,
    bucket_name,
    key_prefix,
    destination,
    *,
    policy=None,
    client_factory=boto3.client,
):
    """Download one delivery and return files plus its processing directory."""

    effective_policy = policy or S3DownloadPolicy.from_environment()
    endpoint = effective_policy.authorize(host)
    _validate_credentials_and_location(
        access_key,
        secret_key,
        bucket_name,
        key_prefix,
    )
    destination = prepare_destination(destination)
    client = create_client(
        endpoint,
        access_key,
        secret_key,
        effective_policy,
        client_factory,
    )

    created_paths = []
    try:
        response = client.list_objects_v2(
            Bucket=bucket_name,
            Prefix=key_prefix,
            MaxKeys=effective_policy.max_objects,
        )
        objects = validate_object_listing(
            response,
            prefix=key_prefix,
            policy=effective_policy,
        )
        downloaded_total = 0
        for item in objects:
            local_path, downloaded_total = download_object(
                client,
                bucket_name,
                item,
                destination,
                downloaded_total,
                effective_policy.max_download_bytes,
            )
            created_paths.append(local_path)

        if len(created_paths) == 1 and created_paths[0].suffix.casefold() == ".zip":
            archive_path = created_paths[0]
            digest = hash_file(archive_path)
            extraction_dir = destination.joinpath("archive")
            safely_extract_zip(archive_path, extraction_dir)
            archive_path.unlink()
            created_paths.remove(archive_path)
            return S3DownloadResult(
                digest=digest,
                hash_files=(archive_path.name,),
                processing_dir=extraction_dir,
            )

        return S3DownloadResult(
            digest=hash_files(created_paths),
            hash_files=tuple(path.name for path in created_paths),
            processing_dir=destination,
        )
    except S3DownloadError:
        remove_created_files(created_paths, logger)
        raise
    except UnsafeArchiveError as exc:
        remove_created_files(created_paths, logger)
        raise rejected_delivery("unsafe archive") from exc
    except Exception as exc:
        remove_created_files(created_paths, logger)
        raise upstream_error(type(exc).__name__) from exc


def do_s3_download(
    host,
    access_key,
    secret_key,
    bucketname,
    pattern,
    s3_local_dir,
    status,
):
    """Adapt the secure downloader to the legacy QC check-status protocol."""

    try:
        result = download_s3_delivery(
            host,
            access_key,
            secret_key,
            bucketname,
            pattern,
            s3_local_dir,
        )
    except S3DownloadError as exc:
        logger.warning("S3 delivery download rejected (%s).", exc.code)
        status.aborted(exc.public_message)
        return
    except Exception as exc:
        logger.warning(
            "Unexpected S3 delivery download failure (%s).",
            type(exc).__name__,
        )
        status.aborted(S3DownloadError.public_message)
        return

    if not status.params.get("hash"):
        status.set_status_property("hash", result.digest)
        status.set_status_property("hash_files", list(result.hash_files))
    if not status.params.get("unzip_dir"):
        status.add_params({"unzip_dir": result.processing_dir})


def _validate_credentials_and_location(access_key, secret_key, bucket_name, key_prefix):
    values = (
        (access_key, 100),
        (secret_key, 4096),
        (bucket_name, 63),
        (key_prefix, 1024),
    )
    for value, maximum in values:
        if (
            not isinstance(value, str)
            or not value
            or len(value) > maximum
            or value != value.strip()
            or not value.isprintable()
        ):
            raise rejected_delivery("S3 credentials or location are invalid")
    if "/" in bucket_name or "\\" in bucket_name or "\\" in key_prefix:
        raise rejected_delivery("S3 bucket or prefix is invalid")
