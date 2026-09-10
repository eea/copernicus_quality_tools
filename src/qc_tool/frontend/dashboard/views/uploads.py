"""Resumable browser-upload pages and chunk endpoints."""

import json

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.db import transaction
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse

from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.services.uploads import ResumableUploadDescriptor
from qc_tool.frontend.dashboard.services.uploads import ResumableUploadError
from qc_tool.frontend.dashboard.services.uploads import prepare_resumable_paths
from qc_tool.frontend.dashboard.services.uploads.registration import probe_registered_chunk, receive_registered_chunk
from qc_tool.frontend.dashboard.services.uploads.resumable import validate_delivery_filename
from qc_tool.frontend.dashboard.services.uploads.overwrite import overwrite_reason


MAX_CHECK_BYTES = 64 * 1024


def delivery_upload_check(request):
    """Check filename collisions in the authenticated user's deliveries only."""

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
    ).only("pk", "filename", "date_uploaded", "date_submitted", "s3_id").order_by("-date_uploaded", "-pk"):
        if delivery.filename in existing:
            ambiguous.add(delivery.filename)
        existing.setdefault(delivery.filename, delivery)
    files = []
    for filename in filenames:
        delivery = existing.get(filename)
        reason = ""
        if delivery is not None:
            reason = "Multiple deliveries have this filename. Use a different filename or resolve the existing records first." if filename in ambiguous else overwrite_reason(delivery)
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
    return render(request, 'dashboard/deliveries/upload.html', {
        'resumable_simultaneous_uploads': settings.RESUMABLE_SIMULTANEOUS_UPLOADS
    })


@transaction.non_atomic_requests
def resumable_upload(request):
    parameters = request.GET if request.method == "GET" else request.POST
    try:
        descriptor = ResumableUploadDescriptor.from_mapping(parameters)

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
