"""Recoverable registration of browser uploads under one upload lock."""

import json
import os
import stat

from django.db import transaction

from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.services.products import find_product_description, guess_product_ident

from ._resumable.assembly import (
    _best_effort_unlink, _discard_published_chunks, owned_publication,
    publish_for_registration,
)
from ._resumable.chunks import is_chunk_stored, is_upload_complete, store_chunk
from ._resumable.errors import ResumableUploadError
from ._resumable.filesystem import open_directory, read_flags, write_once_flags
from ._resumable.locks import upload_lock
from ._resumable.paths import expected_chunk_paths
from .locking import delivery_filename_lock, require_available_filename


def probe_registered_chunk(descriptor, paths, *, user):
    """A final chunk is complete only after a live delivery was registered."""

    if not paths.chunks_dir.exists():
        return False
    with delivery_filename_lock(paths.user_root, descriptor.filename) as filename_directory, upload_lock(paths.chunks_dir) as directory:
        require_available_filename(filename_directory, storage_key=descriptor.storage_key if descriptor.overwrite_delivery_id else None)
        if descriptor.overwrite_delivery_id is not None:
            from .overwrite import probe_overwrite_chunk
            return probe_overwrite_chunk(descriptor, paths, user=user, directory=directory, filename_directory=filename_directory)
        receipt = _read_receipt(directory)
        if receipt is not None:
            return _registered_delivery(receipt, paths, user) is not None
        if _active_delivery(paths, user) is not None:
            target_directory = open_directory(paths.user_root)
            try:
                pending = _read_receipt(directory, filename=".registration")
                if (owned_publication(paths, directory, target_directory)
                        and pending is not None
                        and _registered_delivery(pending, paths, user) is not None):
                    return False
            finally:
                os.close(target_directory)
            raise _delivery_exists()
        # Always require one POST to finalize fully staged, unregistered bytes.
        return descriptor.chunk_number != descriptor.total_chunks and is_chunk_stored(paths.chunk_path)


def receive_registered_chunk(descriptor, paths, *, user, uploaded_chunk):
    """Store, assemble and register once; retries recover any prior publication."""

    with delivery_filename_lock(paths.user_root, descriptor.filename) as filename_directory, upload_lock(paths.chunks_dir) as directory:
        require_available_filename(filename_directory, storage_key=descriptor.storage_key if descriptor.overwrite_delivery_id else None)
        if descriptor.overwrite_delivery_id is not None:
            from .overwrite import receive_overwrite_chunk
            return receive_overwrite_chunk(descriptor, paths, user=user, uploaded_chunk=uploaded_chunk, directory=directory, filename_directory=filename_directory)
        receipt = _read_receipt(directory)
        if receipt is not None:
            registered = _registered_delivery(receipt, paths, user)
            if registered is not None:
                return registered
            # A completed upload was removed. Its old chunks cannot be resumed
            # into a new delivery, even when the client reuses its identifier.
            _discard_published_chunks(directory, expected_chunk_paths(descriptor, paths))
            _best_effort_unlink(directory, ".assembled")
            _best_effort_unlink(directory, ".registration")
            os.unlink(".registered", dir_fd=directory)

        target_directory = open_directory(paths.user_root)
        try:
            owned = owned_publication(paths, directory, target_directory)
        finally:
            os.close(target_directory)
        active = _active_delivery(paths, user)
        pending = _read_receipt(directory, filename=".registration")
        if active is not None:
            if (not owned or pending is None
                    or _registered_delivery(pending, paths, user) is None
                    or pending["delivery_id"] != active.pk):
                raise _delivery_exists()
        if not owned:
            store_chunk(uploaded_chunk, paths.chunk_path, expected_bytes=descriptor.current_chunk_size)
            if not is_upload_complete(descriptor, paths):
                return None
        target = publish_for_registration(descriptor, paths, directory)
        try:
            with transaction.atomic(durable=True):
                delivery = _active_delivery(paths, user)
                if delivery is not None:
                    if (not owned or pending is None
                            or pending["delivery_id"] != delivery.pk
                            or _registered_delivery(pending, paths, user) is None):
                        raise _delivery_exists()
                else:
                    product_ident = guess_product_ident(target)
                    delivery = Delivery.objects.create(
                        filename=target.name, size_bytes=target.stat().st_size,
                        product_ident=product_ident,
                        product_description=find_product_description(product_ident),
                        user=user, is_deleted=False,
                    )
                    # Record the allocated identity before commit. If commit
                    # succeeds but its response is lost, a retry may recover
                    # this exact row and must not adopt another same-name row.
                    _write_pending_registration(directory, paths, delivery)
        except ResumableUploadError:
            raise
        except Exception as exc:
            # Keep both chunks and the owned inode for a safe POST retry.
            raise ResumableUploadError(
                "delivery_registration_failed",
                "The upload is stored but could not be registered. Retry the upload to finish.", 500,
            ) from exc
        try:
            _write_receipt(directory, paths, delivery)
        except OSError as exc:
            raise ResumableUploadError(
                "upload_confirmation_failed",
                "The delivery was registered but upload confirmation failed. Retry to confirm it.", 503,
            ) from exc
        _discard_published_chunks(directory, expected_chunk_paths(descriptor, paths))
        _best_effort_unlink(directory, ".assembled")
        _best_effort_unlink(directory, ".registration")
        return delivery


def _active_delivery(paths, user):
    return Delivery.objects.filter(user_id=user.pk, filename=paths.target_path.name, is_deleted=False).first()


def _registered_delivery(receipt, paths, user):
    target_directory = open_directory(paths.user_root)
    try:
        try:
            target = os.stat(paths.target_path.name, dir_fd=target_directory, follow_symlinks=False)
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(target.st_mode):
            raise ResumableUploadError("unsafe_upload_storage", "Upload storage is not safe.", 500)
        if [target.st_dev, target.st_ino, target.st_size] != receipt["file"]:
            return None
    finally:
        os.close(target_directory)
    return Delivery.objects.filter(
        pk=receipt["delivery_id"], user_id=user.pk,
        filename=paths.target_path.name, is_deleted=False,
    ).first()


def _read_receipt(directory, *, filename=".registered"):
    try:
        descriptor = os.open(filename, read_flags() | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ResumableUploadError("unsafe_upload_staging", "The upload registration receipt cannot be read safely.", 500) from exc
    try:
        with os.fdopen(descriptor, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ValueError("unsafe receipt")
            data = json.loads(source.read(1025))
        if (
            not isinstance(data, dict) or type(data.get("delivery_id")) is not int
            or data["delivery_id"] < 1 or not isinstance(data.get("file"), list)
            or len(data["file"]) != 3 or any(type(value) is not int or value < 0 for value in data["file"])
        ):
            raise ValueError("invalid receipt")
        return data
    except (ValueError, UnicodeError, OSError) as exc:
        raise ResumableUploadError("unsafe_upload_staging", "The upload registration receipt is invalid.", 500) from exc


def _write_receipt(directory, paths, delivery):
    _write_registration_identity(directory, paths, delivery, filename=".registered")


def _write_pending_registration(directory, paths, delivery):
    _write_registration_identity(directory, paths, delivery, filename=".registration")


def _write_registration_identity(directory, paths, delivery, *, filename):
    target = paths.target_path.stat(follow_symlinks=False)
    payload = json.dumps({"delivery_id": delivery.pk, "file": [target.st_dev, target.st_ino, target.st_size]}).encode()
    temporary_name = filename + ".tmp"
    _best_effort_unlink(directory, temporary_name)
    descriptor = os.open(temporary_name, write_once_flags(), 0o600, dir_fd=directory)
    with os.fdopen(descriptor, "wb") as destination:
        destination.write(payload)
        destination.flush()
        os.fsync(destination.fileno())
    os.replace(temporary_name, filename, src_dir_fd=directory, dst_dir_fd=directory)
    os.fsync(directory)


def _delivery_exists():
    return ResumableUploadError(
        "delivery_exists", "You already have a delivery with this filename. View the existing delivery or rename the new ZIP before adding it.", 409,
    )
