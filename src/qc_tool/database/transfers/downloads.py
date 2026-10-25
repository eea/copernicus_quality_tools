"""Authenticated delivery of retained ZIP bytes, including resumable ranges.

Preparation is never called here. A disconnected client closes only its own
file handle; the immutable package and background operation remain available.
"""

import os
import re

from django.http import FileResponse, HttpResponse, StreamingHttpResponse
from django.utils.http import content_disposition_header, http_date, parse_http_date_safe


BLOCK_SIZE = 256 * 1024
_RANGE = re.compile(r"bytes=([0-9]*)-([0-9]*)\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class _FileRange:
    def __init__(self, handle, length):
        self.handle, self.remaining = handle, length

    def __iter__(self):
        return self

    def __next__(self):
        if self.remaining <= 0:
            raise StopIteration
        block = self.handle.read(min(BLOCK_SIZE, self.remaining))
        if not block:
            raise StopIteration
        self.remaining -= len(block)
        return block

    def close(self):
        self.handle.close()


def _range(value, size):
    match = _RANGE.fullmatch(value) if len(value) <= 128 else None
    if match is None or not any(match.groups()) or size == 0:
        raise ValueError("Unsupported byte range.")
    first, last = match.groups()
    if not first:
        length = int(last)
        if length <= 0:
            raise ValueError("Invalid suffix range.")
        return max(0, size - length), size - 1
    start, end = int(first), min(int(last), size - 1) if last else size - 1
    if start >= size or end < start:
        raise ValueError("Unsatisfiable byte range.")
    return start, end


def response(handle, metadata, request):
    """Return a full/range/HEAD response using an already authorized open file."""
    status = os.fstat(handle.fileno())
    size = status.st_size
    checksum = metadata.get("sha256")
    etag = ('"sha256-' + checksum + '"') if isinstance(checksum, str) and _DIGEST.fullmatch(checksum) else (
        'W/"' + str(size) + '-' + str(status.st_mtime_ns) + '"')
    headers = {"Content-Type": "application/zip", "Content-Length": str(size),
               "Content-Disposition": content_disposition_header(True, metadata["filename"]),
               "Accept-Ranges": "bytes", "ETag": etag, "Last-Modified": http_date(status.st_mtime),
               "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}
    requested = request.headers.get("Range")
    if_range = request.headers.get("If-Range")
    if requested and if_range:
        if if_range.startswith(('"', 'W/')):
            matches = not if_range.startswith('W/') and if_range == etag
        else:
            date = parse_http_date_safe(if_range)
            matches = date is not None and int(status.st_mtime) <= date
        if not matches:
            requested = None
    if requested:
        try:
            start, end = _range(requested, size)
        except ValueError:
            handle.close()
            headers.update({"Content-Range": "bytes */" + str(size), "Content-Length": "0"})
            return HttpResponse(status=416, headers=headers)
        length = end - start + 1
        headers.update({"Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(length)})
        if request.method == "HEAD":
            handle.close()
            return HttpResponse(status=206, headers=headers)
        handle.seek(start)
        return StreamingHttpResponse(_FileRange(handle, length), status=206, headers=headers)
    if request.method == "HEAD":
        handle.close()
        return HttpResponse(headers=headers)
    handle.seek(0)
    result = FileResponse(handle, as_attachment=True, filename=metadata["filename"], headers=headers)
    result.block_size = BLOCK_SIZE
    return result
