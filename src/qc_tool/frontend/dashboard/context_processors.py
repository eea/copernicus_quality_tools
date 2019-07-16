from django.conf import settings # import the settings file
from qc_tool.common import get_qc_tool_version

def show_logo(request):
    # return the value you want as a dictionnary. you may add multiple values in there.
    return {'SHOW_LOGO': settings.SHOW_LOGO != "no"}

def version_processor(request):
    return {'qc_tool_version': get_qc_tool_version()}