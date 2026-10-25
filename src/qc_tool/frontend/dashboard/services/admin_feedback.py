"""Shared presentation for temporarily busy administrative actions."""

from django.urls import reverse


def busy_context(error):
    """Recognize typed admission errors through service translation boundaries."""
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if getattr(error, "code", None) == "maintenance_busy":
            return {"admin_busy": True, "admin_busy_status_url": reverse("admin_maintenance")}
        error = error.__cause__
    return {}
