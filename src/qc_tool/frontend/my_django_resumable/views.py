import logging
from pathlib import Path
from django.conf import settings
from django.http import HttpResponse

from qc_tool.frontend.my_django_resumable.files import ResumableFile
from qc_tool.frontend.my_django_resumable.files import get_storage

#from .files import ResumableFile, get_storage, get_chunks_upload_to

logger = logging.getLogger(__name__)


def resumable_upload(request):
    user_upload_path = Path(settings.MEDIA_ROOT).joinpath(request.user.username)
    if not user_upload_path.exists():
        logger.info("Creating a directory for user-uploaded files: {:s}.".format(str(user_upload_path)))
        user_upload_path.mkdir(parents=True)
    upload_to = user_upload_path # Fixme use better setting
    logger.info("upload_to: " + str(upload_to))

    upload_to = None # will use the default MEDIA_ROOT.

    storage = get_storage(upload_to)
    if request.method == 'POST':
        chunk = request.FILES.get('file')
        r = ResumableFile(storage, request.POST)
        if not r.chunk_exists:
            r.process_chunk(chunk)
        if r.is_complete:
            actual_filename = storage.save(r.filename, r.file)
            r.delete_chunks()
            return HttpResponse(storage.url(actual_filename), status=201)
        return HttpResponse('chunk uploaded')
    elif request.method == 'GET':
        r = ResumableFile(storage, request.GET)
        if not r.chunk_exists:
            return HttpResponse('chunk not found', status=404)
        if r.is_complete:
            actual_filename = storage.save(r.filename, r.file)
            r.delete_chunks()
            return HttpResponse(storage.url(actual_filename), status=201)
        return HttpResponse('chunk exists', status=200)
