from urllib.parse import urljoin

from django.conf import settings
from django.forms import FileInput, CheckboxInput, forms
from django.template import loader
from django.templatetags.static import static
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy


class ResumableWidget(FileInput):
    template_name = 'django_resumable/file_input.html'
    clear_checkbox_label = ugettext_lazy('Clear')

    def render(self, name, value, attrs=None, **kwargs):

        if not value:
            file_url = ''
        else:
            if hasattr(value, 'name'):
                file_name = value.name
            else:
                file_name = value
            file_url = urljoin(settings.MEDIA_URL, file_name)

        chunkSize = getattr(settings, 'RESUMABLE_CHUNKSIZE', "1*1024*1024")
        show_thumb = getattr(settings, 'RESUMABLE_SHOW_THUMB', False)
        context = {'name': name,
                   'value': value,
                   'id': attrs['id'],
                   'chunkSize': chunkSize,
                   'show_thumb': show_thumb,
                   'field_name': self.attrs['field_name'],
                   'content_type_id': self.attrs['content_type_id'],
                   'file_url': file_url}

        if not self.is_required:
            template_with_clear = '<span class="clearable-file-input">%(clear)s ' \
                                  '<label for="%(clear_checkbox_id)s">%(clear_checkbox_label)s</label>' \
                                  '</span><br/>'
            substitutions = {}
            substitutions['clear_checkbox_id'] = attrs['id'] + "-clear-id"
            substitutions['clear_checkbox_name'] = attrs['id'] + "-clear"
            substitutions['clear_checkbox_label'] = self.clear_checkbox_label
            substitutions['clear'] = CheckboxInput().render(
                substitutions['clear_checkbox_name'],
                False,
                attrs={'id': substitutions['clear_checkbox_id']}
            )
            clear_checkbox = mark_safe(template_with_clear % substitutions)
            context.update({'clear_checkbox': clear_checkbox})
        return loader.render_to_string(self.template_name, context)

    def value_from_datadict(self, data, files, name):
        if not self.is_required and data.get("id_" + name + "-clear"):
            return False  # False signals to clear any existing value, as opposed to just None
        if data.get(name, None) in ['None', 'False']:
            return None
        return data.get(name, None)

    @property
    def media(self):
        js = ["resumable.js"]
        return forms.Media(js=[static("django_resumable/js/%s" % path) for path in js])