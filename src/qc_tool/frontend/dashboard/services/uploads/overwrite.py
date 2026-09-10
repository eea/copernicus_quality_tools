"""Explicit replacement of an owned delivery, with recoverable publication.

The old row is retired in a durable transaction before changing its filename's
bytes. A private journal ties the retired row, hidden successor and both inodes
together. This prevents a process interruption from attaching old QC to new data.
"""
import json
import os
import stat
from dataclasses import asdict

from django.db import transaction

from qc_tool.common import JOB_RUNNING, JOB_WAITING
from qc_tool.frontend.dashboard.models import Delivery, DeliverySubmission, Job
from qc_tool.frontend.dashboard.services.products import find_product_description, guess_product_ident
from ._resumable.assembly import _discard_stale_assembly, _write_assembly, _discard_published_chunks
from ._resumable.chunks import is_chunk_stored, is_upload_complete, store_chunk
from ._resumable.errors import ResumableUploadError
from ._resumable.filesystem import open_directory, read_flags, write_once_flags
from ._resumable.paths import expected_chunk_paths


def overwrite_reason(delivery):
    if delivery.s3_id is not None:
        return "This delivery uses S3 storage. Add this ZIP with a different filename."
    if delivery.date_submitted is not None or DeliverySubmission.objects.filter(delivery_id=delivery.pk).exists():
        return "This delivery has a submission and is retained. Add this ZIP with a different filename."
    if Job.objects.filter(delivery_id=delivery.pk, job_status__in=(JOB_WAITING, JOB_RUNNING)).exists():
        return "This delivery has waiting or running quality checks. Wait for them to finish before overwriting."
    return ""


def _changed():
    return ResumableUploadError("overwrite_target_changed", "The existing delivery changed. Retry to review it before overwriting.", 409)


def _identity(directory, name):
    value = os.stat(name, dir_fd=directory, follow_symlinks=False)
    if not stat.S_ISREG(value.st_mode):
        raise ResumableUploadError("unsafe_upload_storage", "The delivery file is not safe to replace.", 409)
    return [value.st_dev, value.st_ino, value.st_size]


def _read_journal(directory):
    try:
        fd = os.open(".overwrite", read_flags() | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        return None
    try:
        with os.fdopen(fd, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ValueError("Not a regular journal")
            data = json.loads(source.read(4097))
        if (not isinstance(data, dict) or any(type(data.get(key)) is not int for key in ("original_id", "replacement_id"))
                or not isinstance(data.get("created"), str)
                or any(not isinstance(data.get(key), list) or len(data[key]) != 3
                       or any(type(value) is not int or value < 0 for value in data[key])
                       for key in ("previous", "replacement"))):
            raise ValueError("Invalid journal")
        return data
    except (ValueError, UnicodeError) as exc:
        raise ResumableUploadError("unsafe_upload_staging", "The overwrite recovery record is invalid.", 500) from exc


def _write_journal(directory, data):
    # Called only before the retirement transaction commits. A previous rolled
    # back record is discarded only while the original inode is still active.
    try:
        os.unlink(".overwrite.tmp", dir_fd=directory)
    except FileNotFoundError:
        pass
    fd = os.open(".overwrite.tmp", write_once_flags(), 0o600, dir_fd=directory)
    with os.fdopen(fd, "wb") as target:
        target.write(json.dumps(data).encode())
        target.flush()
        os.fsync(target.fileno())
    os.replace(".overwrite.tmp", ".overwrite", src_dir_fd=directory, dst_dir_fd=directory)
    os.fsync(directory)


def _require_original(descriptor, paths, user, *, locked=False):
    query = Delivery.objects.select_for_update() if locked else Delivery.objects
    original = query.filter(pk=descriptor.overwrite_delivery_id, user_id=user.pk,
                            filename=descriptor.filename, is_deleted=False).first()
    if original is None or Delivery.objects.filter(user_id=user.pk, filename=descriptor.filename, is_deleted=False).exclude(pk=original.pk).exists():
        raise _changed()
    reason = overwrite_reason(original)
    if reason:
        raise ResumableUploadError("overwrite_not_allowed", reason, 409)
    return original


def probe_overwrite_chunk(descriptor, paths, *, user, directory, filename_directory):
    from .registration import _read_receipt, _registered_delivery
    receipt = _read_receipt(directory)
    if receipt is not None:
        if _registered_delivery(receipt, paths, user) is None:
            raise _changed()
        return True
    journal = _read_journal(directory)
    if journal is None:
        _require_original(descriptor, paths, user)
    # The final POST recovers a retirement or completes publication; a probe
    # never treats staged replacement bytes as a successful registration.
    return descriptor.chunk_number != descriptor.total_chunks and is_chunk_stored(paths.chunk_path)


def receive_overwrite_chunk(descriptor, paths, *, user, uploaded_chunk, directory, filename_directory):
    from .registration import _read_receipt, _registered_delivery, _write_receipt
    from .locking import require_available_filename, clear_overwrite_intent, mark_overwrite_intent
    require_available_filename(filename_directory, storage_key=descriptor.storage_key)
    receipt = _read_receipt(directory)
    if receipt is not None:
        registered = _registered_delivery(receipt, paths, user)
        if registered is None:
            raise _changed()
        clear_overwrite_intent(filename_directory)
        return registered
    target_directory = open_directory(paths.user_root)
    try:
        journal = _read_journal(directory)
        if journal is not None and journal["original_id"] != descriptor.overwrite_delivery_id:
            raise _changed()
        if journal is not None and Delivery.objects.filter(pk=journal["original_id"], is_deleted=False).exists():
            # A retirement transaction rolled back. Its source must still be
            # intact before starting another attempt; never adopt its old PK.
            if _identity(target_directory, descriptor.filename) != journal["previous"]:
                raise _changed()
            replacement = Delivery.objects.filter(
                pk=journal["replacement_id"], user_id=user.pk, filename=descriptor.filename,
                date_uploaded=journal["created"], size_bytes=descriptor.total_size, is_deleted=True,
            ).first()
            if replacement is None:
                os.unlink(".overwrite", dir_fd=directory)
                journal = None
            else:
                mark_overwrite_intent(filename_directory, descriptor.storage_key)
                with transaction.atomic(durable=True):
                    original = _require_original(descriptor, paths, user, locked=True)
                    original.is_deleted = True
                    original.save(update_fields=("is_deleted",))
        if journal is None:
            _require_original(descriptor, paths, user)
            if uploaded_chunk is not None:
                store_chunk(uploaded_chunk, paths.chunk_path, expected_bytes=descriptor.current_chunk_size)
            elif not is_upload_complete(descriptor, paths):
                raise ResumableUploadError("upload_incomplete", "The staged replacement is incomplete. Resume the browser upload with its selected ZIP.", 409)
            if not is_upload_complete(descriptor, paths):
                return None
            _discard_stale_assembly(directory)
            _write_assembly(descriptor, expected_chunk_paths(descriptor, paths), directory)
            previous = _identity(target_directory, descriptor.filename)
            # Preserve the old raw archive as a private audit/recovery copy.
            try:
                os.link(descriptor.filename, ".previous", src_dir_fd=target_directory, dst_dir_fd=directory, follow_symlinks=False)
            except FileExistsError:
                if _identity(directory, ".previous") != previous:
                    raise _changed()
            if _identity(directory, ".previous") != previous:
                raise _changed()
            os.fsync(directory)
            mark_overwrite_intent(filename_directory, descriptor.storage_key)
            with transaction.atomic(durable=True):
                original = _require_original(descriptor, paths, user, locked=True)
                if _identity(target_directory, descriptor.filename) != previous:
                    raise _changed()
                product_ident = guess_product_ident(paths.target_path)
                replacement = Delivery.objects.create(
                    user=user, filename=descriptor.filename, size_bytes=descriptor.total_size,
                    product_ident=product_ident, product_description=find_product_description(product_ident), is_deleted=True,
                )
                journal = {"original_id": original.pk, "replacement_id": replacement.pk,
                           "created": replacement.date_uploaded.isoformat(), "previous": previous,
                           "replacement": _identity(directory, ".assembled"), "descriptor": asdict(descriptor)}
                _write_journal(directory, journal)
                original.is_deleted = True
                original.save(update_fields=("is_deleted",))
        # At this point retirement is committed. Old QC cannot authorize these
        # bytes even if this process stops between rename and activation.
        with transaction.atomic(durable=True):
            original = Delivery.objects.select_for_update().get(pk=journal["original_id"])
            replacement = Delivery.objects.select_for_update().filter(
                pk=journal["replacement_id"], user_id=user.pk, filename=descriptor.filename,
                date_uploaded=journal["created"], size_bytes=descriptor.total_size,
            ).first()
            if not original.is_deleted or replacement is None:
                raise _changed()
            if Delivery.objects.filter(user_id=user.pk, filename=descriptor.filename, is_deleted=False).exclude(pk=replacement.pk).exists():
                raise _changed()
            current = _identity(target_directory, descriptor.filename)
            if current == journal["previous"]:
                if _identity(directory, ".assembled") != journal["replacement"]:
                    raise _changed()
                # Retain .assembled for confirmation recovery after the rename.
                try:
                    os.unlink(".publishing", dir_fd=directory)
                except FileNotFoundError:
                    pass
                os.link(".assembled", ".publishing", src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
                os.replace(".publishing", descriptor.filename, src_dir_fd=directory, dst_dir_fd=target_directory)
                os.fsync(target_directory)
            elif current != journal["replacement"]:
                raise _changed()
            replacement.is_deleted = False
            replacement.save(update_fields=("is_deleted",))
        _write_receipt(directory, paths, replacement)
        clear_overwrite_intent(filename_directory)
        _discard_published_chunks(directory, expected_chunk_paths(descriptor, paths))
        return replacement
    except ResumableUploadError:
        _restore_unconfirmed_original(descriptor, paths, user, directory, target_directory)
        _release_unretired_intent(descriptor, user, filename_directory)
        raise
    except Exception as exc:
        _restore_unconfirmed_original(descriptor, paths, user, directory, target_directory)
        _release_unretired_intent(descriptor, user, filename_directory)
        raise ResumableUploadError("overwrite_confirmation_failed", "The overwrite could not be confirmed. Retry this upload to recover it; both archives are retained safely.", 503) from exc
    finally:
        os.close(target_directory)


def _release_unretired_intent(descriptor, user, filename_directory):
    """Do not strand a filename when retirement itself was rejected/rolled back."""
    from .locking import clear_overwrite_intent
    try:
        if Delivery.objects.filter(pk=descriptor.overwrite_delivery_id, user_id=user.pk, is_deleted=False).exists():
            clear_overwrite_intent(filename_directory)
    except Exception:
        # If the database is unavailable, keep the recovery guard. This same
        # upload can retry once it returns; another upload must not take over.
        pass


def _restore_unconfirmed_original(descriptor, paths, user, directory, target_directory):
    """On a recoverable failure, keep the previous delivery usable when possible.

    A committed successor is never rolled back. If recovery itself cannot run,
    leave the journal and retirement in place for a later retry to finish safely.
    """
    try:
        journal = _read_journal(directory)
        if journal is None:
            return
        with transaction.atomic(durable=True):
            original = Delivery.objects.select_for_update().filter(
                pk=journal["original_id"], user_id=user.pk, filename=descriptor.filename,
                is_deleted=True,
            ).first()
            successor = Delivery.objects.select_for_update().filter(
                pk=journal["replacement_id"], user_id=user.pk, filename=descriptor.filename,
                date_uploaded=journal["created"], is_deleted=True,
            ).first()
            if original is None or successor is None or Delivery.objects.filter(
                    user_id=user.pk, filename=descriptor.filename, is_deleted=False).exists():
                return
            current = _identity(target_directory, descriptor.filename)
            if current not in (journal["previous"], journal["replacement"]):
                return
            if _identity(directory, ".previous") != journal["previous"]:
                return
            if current == journal["replacement"]:
                try:
                    os.unlink(".restoring", dir_fd=directory)
                except FileNotFoundError:
                    pass
                os.link(".previous", ".restoring", src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
                os.replace(".restoring", descriptor.filename, src_dir_fd=directory, dst_dir_fd=target_directory)
                os.fsync(target_directory)
            original.is_deleted = False
            original.save(update_fields=("is_deleted",))
    except Exception:
        pass
