"""Bounded transfer of one validated S3 object."""

import os
import stat

from .errors import rejected_delivery
from .errors import upstream_error
from .storage import open_directory


COPY_CHUNK_BYTES = 1024 * 1024


def download_object(client, bucket_name, item, destination, total, maximum):
    """Download one immutable listing entry into a no-follow file."""

    arguments = {"Bucket": bucket_name, "Key": item.key}
    if item.etag:
        arguments["IfMatch"] = item.etag
    response = client.get_object(**arguments)
    if not isinstance(response, dict):
        raise upstream_error("object response is invalid")
    content_length = response.get("ContentLength")
    body = response.get("Body")
    if (
        not isinstance(content_length, int)
        or isinstance(content_length, bool)
        or content_length != item.size
        or body is None
        or not callable(getattr(body, "read", None))
    ):
        raise rejected_delivery("object changed between listing and download")

    directory_descriptor = open_directory(destination)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = None
    downloaded = 0
    try:
        descriptor = os.open(item.filename, flags, 0o600, dir_fd=directory_descriptor)
        with os.fdopen(descriptor, "wb") as output:
            descriptor = None
            while True:
                chunk = body.read(COPY_CHUNK_BYTES)
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    raise upstream_error("object body returned non-bytes")
                downloaded += len(chunk)
                if downloaded > item.size or total + downloaded > maximum:
                    raise rejected_delivery("object exceeded its size limit")
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if downloaded != item.size:
            raise rejected_delivery("object size differs from listing")
        file_stat = os.stat(
            item.filename,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size != item.size:
            raise rejected_delivery("downloaded object is not a regular file")
    except Exception:
        try:
            os.unlink(item.filename, dir_fd=directory_descriptor)
        except FileNotFoundError:
            pass
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)
        close = getattr(body, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
        os.close(directory_descriptor)
    return destination.joinpath(item.filename), total + downloaded
