from django.conf import settings # import the settings file
from qc_tool.common import get_qc_tool_version

def show_logo(request):
    # return the value you want as a dictionnary. you may add multiple values in there.
    return {'SHOW_LOGO': settings.SHOW_LOGO != "no"}

def version_processor(request):
    return {'qc_tool_version': get_qc_tool_version()}

def can_change_password(request):
    """Context processor to determine if user can change their password."""
    can_change = True
    if request.user.is_authenticated:
        # Users in test_group or guest_group cannot change password
        can_change = not request.user.groups.filter(name__in=['test_group', 'guest_group']).exists()
    return {'can_change_password': can_change}