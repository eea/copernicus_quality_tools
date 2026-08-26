"""Resumable browser-upload pages and chunk endpoints."""

import logging
from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
import qc_tool.frontend.dashboard.models as models
from qc_tool.frontend.dashboard.services.products import find_product_description
from qc_tool.frontend.dashboard.services.products import guess_product_ident
from qc_tool.frontend.dashboard.services.uploads import ResumableUploadDescriptor
from qc_tool.frontend.dashboard.services.uploads import ResumableUploadError
from qc_tool.frontend.dashboard.services.uploads import assemble_chunks
from qc_tool.frontend.dashboard.services.uploads import is_chunk_stored
from qc_tool.frontend.dashboard.services.uploads import is_upload_complete
from qc_tool.frontend.dashboard.services.uploads import prepare_resumable_paths
from qc_tool.frontend.dashboard.services.uploads import remove_published_upload
from qc_tool.frontend.dashboard.services.uploads import store_chunk

logger = logging.getLogger(__name__)


def resumable_upload_page(request):
    """
    Resumable file upload demo.
    """
    return render(request, 'dashboard/deliveries/upload.html', {
        'resumable_simultaneous_uploads': settings.RESUMABLE_SIMULTANEOUS_UPLOADS
    })


def uploaded_delivery_file_exists(filename, user_id):
    """
    Helper function used by resumable_upload.
    :param filename: the uploaded .zip file name.
    :param username: the user id.
    :return: Returns: an error message if delivery with same filename and username already exists in the DB.
    """
    existing_deliveries = models.Delivery.objects.filter(
        filename=filename, user_id=user_id).exclude(is_deleted=True)
    if existing_deliveries.count() > 0:
        logger.info("Upload rejected: file {} already exists for user_id={}".format(filename, user_id))

        file_exists_message = "A file named {} already exists. \
                            If you want to replace the file, please delete if first.".format(filename)
        return file_exists_message


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
            if is_chunk_stored(paths.chunk_path):
                return HttpResponse(status=200)
            return HttpResponse(status=404)

        conflict_message = uploaded_delivery_file_exists(
            descriptor.filename,
            request.user.id,
        )
        if conflict_message:
            return JsonResponse(
                {
                    "status": "error",
                    "code": "delivery_exists",
                    "message": conflict_message,
                },
                status=409,
            )

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
        store_chunk(
            uploaded_chunk,
            paths.chunk_path,
            expected_bytes=descriptor.current_chunk_size,
        )
        if is_upload_complete(descriptor, paths):
            target_filepath = assemble_chunks(descriptor, paths)
            try:
                product_ident = guess_product_ident(target_filepath)
                product_description = find_product_description(product_ident)
                with transaction.atomic():
                    models.Delivery.objects.create(
                        filename=target_filepath.name,
                        size_bytes=target_filepath.stat().st_size,
                        product_ident=product_ident,
                        product_description=product_description,
                        date_uploaded=timezone.now(),
                        user=request.user,
                        is_deleted=False,
                    )
            except Exception as exc:
                try:
                    remove_published_upload(paths, target_filepath)
                except ResumableUploadError:
                    logger.exception(
                        "Failed to remove an unregistered delivery upload for user_id=%s",
                        request.user.id,
                    )
                raise ResumableUploadError(
                    "delivery_registration_failed",
                    "The uploaded delivery could not be registered.",
                    500,
                ) from exc

        return JsonResponse(
            {"status": "ok", "message": "Chunk uploaded successfully."},
            status=200,
        )
    except ResumableUploadError as exc:
        return JsonResponse(
            {"status": "error", "code": exc.code, "message": exc.message},
            status=exc.status_code,
        )
