from django.conf import settings # import the settings file
from qc_tool.common import get_qc_tool_version

def show_logo(request):
    # return the value you want as a dictionnary. you may add multiple values in there.
    return {'SHOW_LOGO': settings.SHOW_LOGO != "no"}

def organization(request):
    return {'ORGANIZATION': settings.ORGANIZATION}

def copyright(request):
    return {'COPYRIGHT': settings.COPYRIGHT}

def version_processor(request):
    return {'qc_tool_version': get_qc_tool_version()}

def can_change_password(request):
    """Context processor to determine if user can change their password."""
    can_change = True
    if request.user.is_authenticated:
        # Users in test_group or guest_group cannot change password
        can_change = not request.user.groups.filter(name__in=['test_group', 'guest_group']).exists()
    return {'can_change_password': can_change}

def header_logos(request):
    raw_logo_names = getattr(settings, 'HEADER_IMAGE_NAMES', '')
    header_logos = []
    
    if raw_logo_names:
        logo_names = [name.strip() for name in str(raw_logo_names).split(',') if name.strip()]
        header_logos = [f"{settings.MEDIA_URL}{name}" for name in logo_names]

    return {
        'HEADER_LOGOS': header_logos,
    }

def footer_logos(request):
    raw_logo_names = getattr(settings, 'FOOTER_IMAGE_NAMES', '')
    footer_logos = []
    
    if raw_logo_names:
        logo_names = [name.strip() for name in str(raw_logo_names).split(',') if name.strip()]
        footer_logos = [f"{settings.MEDIA_URL}{name}" for name in logo_names]

    return {
        'FOOTER_LOGOS': footer_logos,
    }