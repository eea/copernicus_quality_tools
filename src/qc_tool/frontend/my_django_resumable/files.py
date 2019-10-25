# -*- coding: utf-8 -*-
import os
from urllib.parse import urljoin

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.files.storage import get_storage_class


class ResumableFile:

    def __init__(self, storage, kwargs):
        self.storage = storage
        self.kwargs = kwargs
        self.chunk_suffix = "_part_"

    @property
    def chunk_exists(self):
        """Checks if the requested chunk exists.
        """
        return self.storage.exists(self.current_chunk_name) and \
               self.storage.size(self.current_chunk_name) == int(self.kwargs.get('resumableCurrentChunkSize'))

    @property
    def chunk_names(self):
        """Iterates over all stored chunks.
        """
        chunks = []
        files = sorted(self.storage.listdir('')[1])
        for f in files:
            if f.startswith('{}{}'.format(
                    self.filename, self.chunk_suffix)):
                chunks.append(f)
        return chunks

    @property
    def current_chunk_name(self):
        return "%s%s%s" % (
            self.filename,
            self.chunk_suffix,
            self.kwargs.get('resumableChunkNumber').zfill(4)
        )

    def chunks(self):
        """Iterates over all stored chunks.
        """
        files = sorted(self.storage.listdir('')[1])
        for f in files:
            if f.startswith('{}{}'.format(
                    self.filename, self.chunk_suffix)):
                yield self.storage.open(f, 'rb').read()

    def delete_chunks(self):
        [self.storage.delete(chunk) for chunk in self.chunk_names]

    @property
    def file(self):
        """Gets the complete file.
        """
        if not self.is_complete:
            raise Exception('Chunk(s) still missing')
        return self

    @property
    def filename(self):
        """Gets the filename."""
        filename = self.kwargs.get('resumableFilename')
        if '/' in filename:
            raise Exception('Invalid filename')
        return "%s_%s" % (
            self.kwargs.get('resumableTotalSize'),
            filename
        )

    @property
    def is_complete(self):
        """Checks if all chunks are already stored.
        """
        print("resumableTotalSize", int(self.kwargs.get('resumableTotalSize')), ": size", self.size)
        return int(self.kwargs.get('resumableTotalSize')) == self.size

    def process_chunk(self, file):
        if self.storage.exists(self.current_chunk_name):
            self.storage.delete(self.current_chunk_name)
        self.storage.save(self.current_chunk_name, file)

    @property
    def size(self):
        """Gets chunks size.
        """
        size = 0
        for chunk in self.chunk_names:
            size += self.storage.size(chunk)
        return size


def ensure_dir(f):
    d = os.path.dirname(f)
    os.makedirs(d, exist_ok=True)


def get_chunks_subdir():
    return getattr(settings, 'RESUMABLE_SUBDIR', 'resumable_chunks/')


def get_storage(chunks_upload_to):
    """
    Looks at the ADMIN_RESUMABLE_STORAGE setting and returns
    an instance of the storage class specified.

    Defaults to django.core.files.storage.FileSystemStorage.

    Any custom storage class used here must either be a subclass of
    django.core.files.storage.FileSystemStorage, or accept a location
    init parameter.
    """
    if not chunks_upload_to:
        chunks_upload_to = get_chunks_subdir()
    location = os.path.join(settings.MEDIA_ROOT, chunks_upload_to)
    url_path = urljoin(settings.MEDIA_URL, chunks_upload_to)
    ensure_dir(location)
    storage_class_name = getattr(
        settings,
        'RESUMABLE_STORAGE',
        'django.core.files.storage.FileSystemStorage'
    )
    return get_storage_class(storage_class_name)(
        location=location, base_url=url_path)


def get_chunks_upload_to(request):
    if request.method == 'POST':
        ct_id = request.POST['content_type_id']
        field_name = request.POST['field_name']
    else:
        ct_id = request.GET['content_type_id']
        field_name = request.GET['field_name']

    ct = ContentType.objects.get_for_id(ct_id)
    model_cls = ct.model_class()
    field = model_cls._meta.get_field(field_name)
    return field.chunks_upload_to
