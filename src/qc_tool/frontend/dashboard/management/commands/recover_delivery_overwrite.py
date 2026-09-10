"""Inspect or resume one journaled delivery overwrite without re-uploading bytes."""
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.services.uploads import ResumableUploadDescriptor, ResumableUploadError, prepare_resumable_paths
from qc_tool.frontend.dashboard.services.uploads._resumable.locks import upload_lock
from qc_tool.frontend.dashboard.services.uploads._resumable.paths import _validate_owner
from qc_tool.frontend.dashboard.services.uploads.locking import delivery_filename_lock
from qc_tool.frontend.dashboard.services.uploads.overwrite import _read_journal, receive_overwrite_chunk


class Command(BaseCommand):
    help = "Inspect a retained overwrite journal; --apply finishes its original replacement."

    def add_arguments(self, parser):
        parser.add_argument("--delivery-id", type=int, required=True, help="Original delivery ID, including retired records.")
        parser.add_argument("--upload-key", required=True, help="64-character directory name under the owner's incoming uploads directory.")
        parser.add_argument("--apply", action="store_true", help="Recover the recorded replacement; default is inspection only.")

    def handle(self, *args, **options):
        key = options["upload_key"]
        if not re.fullmatch(r"[a-f0-9]{64}", key):
            raise CommandError("The upload key must be 64 lowercase hexadecimal characters.")
        original = Delivery.objects.select_related("user").filter(pk=options["delivery_id"]).first()
        if original is None or original.user is None:
            raise CommandError("The original delivery and owner must still exist.")
        try:
            _validate_owner(original.user.username)
            root = Path(settings.MEDIA_ROOT).resolve(strict=True)
            chunks = root / original.user.username / "uploads" / key
            with delivery_filename_lock(root / original.user.username, original.filename) as filename_directory:
                with upload_lock(chunks) as directory:
                    journal = _read_journal(directory)
                    if journal is None or journal["original_id"] != original.pk:
                        raise CommandError("No matching overwrite journal exists in that upload directory.")
                    values = journal.get("descriptor", {})
                    if not isinstance(values, dict):
                        raise CommandError("The upload descriptor is invalid.")
                    descriptor = ResumableUploadDescriptor.from_mapping({
                        "resumableIdentifier": values.get("identifier"), "resumableFilename": values.get("filename"),
                        "resumableChunkNumber": values.get("chunk_number"), "resumableChunkSize": values.get("chunk_size"),
                        "resumableCurrentChunkSize": values.get("current_chunk_size"), "resumableTotalChunks": values.get("total_chunks"),
                        "resumableTotalSize": values.get("total_size"), "overwrite_delivery_id": values.get("overwrite_delivery_id"),
                        **({"correction_submission_id": values["correction_submission_id"]}
                           if values.get("correction_submission_id") is not None else {}),
                    })
                    if descriptor.storage_key != key or descriptor.overwrite_delivery_id != original.pk or descriptor.filename != original.filename:
                        raise CommandError("The upload identity does not match this delivery.")
                    paths = prepare_resumable_paths(descriptor, media_root=root, username=original.user.username, create=False)
                    successor = Delivery.objects.filter(pk=journal["replacement_id"], user_id=original.user_id,
                                                        filename=original.filename, date_uploaded=journal["created"]).first()
                    self.stdout.write(f"Owner: {original.user.username}; file: {original.filename}; original: {original.pk}; replacement: {successor.pk if successor else 'retirement not committed'}.")
                    if not options["apply"]:
                        self.stdout.write("Inspection only. --apply publishes the recorded replacement and retains the original archive and QC history.")
                        return
                    result = receive_overwrite_chunk(descriptor, paths, user=original.user, uploaded_chunk=None,
                                                     directory=directory, filename_directory=filename_directory)
                    self.stdout.write(self.style.SUCCESS(f"Replacement delivery {result.pk} is registered. Run fresh quality checks."))
        except (ResumableUploadError, OSError) as exc:
            raise CommandError(str(exc)) from exc
