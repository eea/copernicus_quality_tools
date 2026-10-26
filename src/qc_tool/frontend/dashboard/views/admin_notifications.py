"""Admin-owned publication of the shared workspace announcement."""

import logging

from django.contrib import admin, messages
from django.shortcuts import redirect, render

from qc_tool.common import CONFIG
from qc_tool.frontend.dashboard.forms import AnnouncementForm
from qc_tool.frontend.dashboard.services.configuration import (
    AnnouncementStorageError,
    write_announcement,
)
from qc_tool.frontend.dashboard.services.configuration.presentation import announcement_context


logger = logging.getLogger(__name__)


def notifications(request):
    """Preview the active message and render its bounded publication form."""

    return _render_notifications(request)


def _render_notifications(request, form=None, *, status=200):
    state = announcement_context()
    if form is None:
        form = AnnouncementForm(initial={"announcement_text": state["announcement"]})
    return render(request, "admin/notifications.html", {
        **admin.site.each_context(request),
        **state,
        "title": "Notifications",
        "admin_section": "notifications",
        "announcement_form": form,
    }, status=status)


def update_announcement(request):
    """Publish or explicitly clear the message, preserving failures for retry."""

    action = request.POST.get("action", "publish")
    if action not in {"publish", "clear"}:
        form = AnnouncementForm(request.POST)
        form.is_valid()
        form.add_error(None, "Choose Publish announcement or Remove announcement.")
        return _render_notifications(request, form, status=400)

    form = AnnouncementForm(
        {"announcement_text": ""} if action == "clear" else request.POST,
    )
    if not form.is_valid():
        return _render_notifications(request, form)

    announcement_text = form.cleaned_data["announcement_text"]
    try:
        write_announcement(CONFIG["announcement_path"], announcement_text)
    except AnnouncementStorageError:
        logger.warning("Announcement update was rejected by safe storage.")
        form.add_error(None, "The announcement could not be saved. Please try again.")
        return _render_notifications(request, form, status=503)

    messages.success(
        request, "Announcement updated." if announcement_text else "Announcement removed.",
    )
    return redirect("admin_notifications")
