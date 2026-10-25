from django.conf import settings # import the settings file
from qc_tool.common import get_qc_tool_version
from qc_tool.frontend.accounts.authorization import access_for_request


MAINTENANCE_NOTICE = (
    "Maintenance in progress. You can browse and download existing data. "
    "Changes are temporarily paused."
)
ADMIN_MAINTENANCE_NOTICE = (
    "Creating users, editing records and other changes are paused. "
    "Browsing and downloads remain available."
)


def maintenance_context(request):
    """Present middleware's admission decision and Admin-only navigation hints."""

    status = getattr(request, "maintenance_status", {}) or {}
    enabled = bool(getattr(request, "maintenance_active", False))
    generation = status.get("generation")
    valid_generation = type(generation) is int and generation >= 0
    deployment_enforced = bool(
        getattr(settings, "MAINTENANCE_MODE", False) or status.get("forced", False)
    )
    user = getattr(request, "user", None)
    context = {"maintenance": {
        "enabled": enabled,
        "phase": status.get("phase", "off"),
        "generation": generation if valid_generation else None,
        "deployment_enforced": deployment_enforced,
        "resume_blocked_reason": "",
        "can_disable": bool(
            enabled and status.get("phase") == "ready" and valid_generation
            and not deployment_enforced
            and getattr(user, "is_active", False)
            and getattr(user, "is_staff", False)
            and access_for_request(request).is_administrator
        ),
        "notice": MAINTENANCE_NOTICE,
        "admin_notice": ADMIN_MAINTENANCE_NOTICE,
    }}
    match = getattr(request, "resolver_match", None)
    if match and match.view_name == "admin:index":
        from qc_tool.frontend.dashboard.services.admin_overview import overview_context
        context["admin_overview"] = overview_context(request)
        overview = context["admin_overview"]
        if overview.get("transfer_url") or overview.get("transfer_error"):
            context["maintenance"]["can_disable"] = False
            context["maintenance"]["resume_blocked_reason"] = (
                "A database transfer owns maintenance. Complete or recover it before turning maintenance off."
                if overview.get("transfer_url") else
                "Transfer status is unavailable. Open maintenance settings before resuming changes."
            )
    return context

def show_logo(request):
    # return the value you want as a dictionnary. you may add multiple values in there.
    return {'SHOW_LOGO': settings.SHOW_LOGO != "no"}

def version_processor(request):
    return {'qc_tool_version': get_qc_tool_version()}
