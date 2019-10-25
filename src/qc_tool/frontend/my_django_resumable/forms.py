from django.core.exceptions import ValidationError
from django.forms import FileField

from qc_tool.frontend.my_django_resumable.widgets import ResumableWidget


class FormResumableFileField(FileField):
    widget = ResumableWidget

    def to_python(self, data):
        if self.required:
            if not data or data == "None":
                raise ValidationError(self.error_messages['empty'])
        return data