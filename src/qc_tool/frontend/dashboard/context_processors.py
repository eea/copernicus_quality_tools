from django.conf import settings # import the settings file
from qc_tool.common import get_qc_tool_version


MAINTENANCE_NOTICE = (
    "Maintenance in progress. You can browse and download existing data. "
    "Changes are temporarily paused."
)


def maintenance_context(request):
    """Present middleware's admission decision and Admin-only navigation hints."""

    status = getattr(request, "maintenance_status", {}) or {}
    context = {"maintenance": {
        "enabled": bool(getattr(request, "maintenance_active", False)),
        "phase": status.get("phase", "off"),
        "notice": MAINTENANCE_NOTICE,
    }}
    match = getattr(request, "resolver_match", None)
    if match and match.view_name == "admin:index":
        from qc_tool.frontend.dashboard.services.admin_overview import overview_context
        context["admin_overview"] = overview_context(request)
    return context

def show_logo(request):
    # return the value you want as a dictionnary. you may add multiple values in there.
    return {'SHOW_LOGO': settings.SHOW_LOGO != "no"}

def version_processor(request):
    return {'qc_tool_version': get_qc_tool_version()}
