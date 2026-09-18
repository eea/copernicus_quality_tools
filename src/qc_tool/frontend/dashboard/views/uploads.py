"""Resumable browser-upload pages and chunk endpoints."""

import json
from uuid import UUID

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.db import transaction
from django.http import Http404, HttpResponse
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.services.submissions.access import visible_submissions
from qc_tool.frontend.dashboard.services.submissions.presentation import correction_context
from qc_tool.frontend.dashboard.services.uploads import ResumableUploadDescriptor
from qc_tool.frontend.dashboard.services.uploads import ResumableUploadError
from qc_tool.frontend.dashboard.services.uploads import prepare_resumable_paths
from qc_tool.frontend.dashboard.services.uploads.registration import probe_registered_chunk, receive_registered_chunk
from qc_tool.frontend.dashboard.services.uploads.resumable import validate_delivery_filename
from qc_tool.frontend.dashboard.services.uploads.overwrite import overwrite_reason
from qc_tool.frontend.dashboard.services.uploads.corrections import correction_identifier, require_correction_submission
from qc_tool.frontend.dashboard.services.uploads.access import require_upload_delivery, require_upload_filename


MAX_CHECK_BYTES = 64 * 1024


def delivery_upload_check(request):
    """Check filename collisions in the authenticated user's deliveries only."""

    correction_id = None
    access = access_for_request(request)
    try:
        if request.content_type != "application/json":
            raise ResumableUploadError("invalid_upload_check", "Send the filenames as JSON.", 400)
        declared_size = request.META.get("CONTENT_LENGTH", "")
        if declared_size and (not declared_size.isdecimal() or int(declared_size) > MAX_CHECK_BYTES):
            raise ResumableUploadError("upload_check_too_large", "Check at most 100 filenames at a time.", 413)
        body = request.body
        if len(body) > MAX_CHECK_BYTES:
            raise ResumableUploadError("upload_check_too_large", "Check at most 100 filenames at a time.", 413)
        payload = json.loads(body)
        filenames = payload.get("filenames") if isinstance(payload, dict) else None
        if not isinstance(filenames, list) or not 1 <= len(filenames) <= 100:
            raise ResumableUploadError("invalid_upload_check", "Provide between 1 and 100 filenames.", 400)
        for filename in filenames:
            validate_delivery_filename(filename)
        if "correction_submission_id" in payload:
            correction_id = correction_identifier(payload["correction_submission_id"])
            for filename in filenames:
                submission = require_correction_submission(correction_id, user=request.user, filename=filename)
                if submission.delivery.is_deleted:
                    raise ResumableUploadError(
                        "correction_not_available", "A correction has already been uploaded. Open Deliveries to continue with its quality checks.", 409,
                    )
        for filename in filenames:
            require_upload_filename(access, filename)
    except RequestDataTooBig:
        return JsonResponse({"status": "error", "code": "upload_check_too_large", "message": "Check at most 100 filenames at a time."}, status=413)
    except (ValueError, UnicodeError):
        return JsonResponse({"status": "error", "code": "invalid_upload_check", "message": "The upload check JSON is invalid."}, status=400)
    except ResumableUploadError as exc:
        return JsonResponse({"status": "error", "code": exc.code, "message": exc.message}, status=exc.status_code)

    existing = {}
    ambiguous = set()
    for delivery in Delivery.objects.filter(
        user_id=request.user.pk, is_deleted=False, filename__in=set(filenames),
    ).only("pk", "filename", "date_uploaded", "date_submitted", "s3_id", "product_ident").order_by("-date_uploaded", "-pk"):
        try:
            require_upload_delivery(access, delivery)
        except ResumableUploadError as exc:
            return JsonResponse({"status": "error", "code": exc.code, "message": exc.message}, status=exc.status_code)
        if delivery.filename in existing:
            ambiguous.add(delivery.filename)
        existing.setdefault(delivery.filename, delivery)
    files = []
    for filename in filenames:
        delivery = existing.get(filename)
        reason = ""
        if delivery is not None:
            reason = "Multiple deliveries have this filename. Resolve the existing records first." if filename in ambiguous else overwrite_reason(delivery, correction_submission_id=correction_id)
        files.append({
            "filename": filename, "exists": delivery is not None,
            "delivery_id": delivery.pk if delivery is not None else None,
            "date_uploaded": delivery.date_uploaded.isoformat() if delivery is not None else None,
            "can_overwrite": delivery is not None and not reason,
            "overwrite_reason": reason,
            "url": reverse("job_history", kwargs={"delivery_id": delivery.pk}) if delivery is not None else None,
        })
    response = JsonResponse({"status": "ok", "files": files})
    response["Cache-Control"] = "private, no-store"
    return response


def resumable_upload_page(request):
    """Upload delivery ZIP files with recoverable registration."""
    correction = None
    access = access_for_request(request)
    if "correction_for" in request.GET:
        try:
            submission_id = UUID(request.GET["correction_for"])
        except (ValueError, TypeError, AttributeError):
            raise Http404("Correction unavailable.") from None
        submission = get_object_or_404(visible_submissions(access), pk=submission_id)
        correction = correction_context(submission, access)
        if correction is None:
            raise Http404("Correction unavailable.")
    return render(request, 'dashboard/deliveries/upload.html', {
        'resumable_simultaneous_uploads': settings.RESUMABLE_SIMULTANEOUS_UPLOADS,
        'correction': correction,
        'has_product_assignments': access.has_product_assignments,
    })


@transaction.non_atomic_requests
def resumable_upload(request):
    parameters = request.GET if request.method == "GET" else request.POST
    try:
        descriptor = ResumableUploadDescriptor.from_mapping(parameters)
        if descriptor.correction_submission_id is not None:
            require_correction_submission(
                descriptor.correction_submission_id, user=request.user,
                filename=descriptor.filename, delivery_id=descriptor.overwrite_delivery_id,
                allow_retired=True,
            )
        require_upload_filename(
            access_for_request(request), descriptor.filename,
            overwrite_delivery_id=descriptor.overwrite_delivery_id,
        )

        if request.method == "GET":
            paths = prepare_resumable_paths(
                descriptor,
                media_root=settings.MEDIA_ROOT,
                username=request.user.username,
                create=False,
            )
            if probe_registered_chunk(descriptor, paths, user=request.user):
                return HttpResponse(status=200)
            return HttpResponse(status=404)

        uploaded_chunk = request.FILES.get("file")
        if uploaded_chunk is None:
            raise ResumableUploadError(
                "missing_upload_chunk",
                "The upload chunk is required.",
            )

        paths = prepare_resumable_paths(
            descriptor,
            media_root=settings.MEDIA_ROOT,
            username=request.user.username,
            create=True,
        )
        delivery = receive_registered_chunk(
            descriptor, paths, user=request.user, uploaded_chunk=uploaded_chunk,
        )

        return JsonResponse(
            {"status": "ok", "message": "Chunk uploaded successfully.",
             "delivery_id": delivery.pk if delivery is not None else None},
            status=200,
        )
    except ResumableUploadError as exc:
        return JsonResponse(
            {"status": "error", "code": exc.code, "message": exc.message},
            status=exc.status_code,
        )
    except OSError:
        return JsonResponse(
            {
                "status": "error", "code": "upload_storage_error",
                "message": "Upload storage is temporarily unavailable. Retry the upload to finish.",
            },
            status=503,
        )
