"""Workspace configuration pages."""

import logging
from django.contrib import messages
from django.shortcuts import redirect
from django.shortcuts import render
from qc_tool.common import CONFIG
from qc_tool.frontend.dashboard.forms import AnnouncementForm
from qc_tool.frontend.dashboard.services.configuration import AnnouncementStorageError
from qc_tool.frontend.dashboard.services.configuration import read_announcement
from qc_tool.frontend.dashboard.services.configuration import write_announcement

logger = logging.getLogger(__name__)


def announcement(request):
    """Render the current announcement for an authenticated QC Tool user."""

    return _render_announcement(request)


def _render_announcement(request, announcement_form=None):
    """Render current state and an optional bound operator form."""

    announcement_available = True
    try:
        announcement_message = read_announcement(CONFIG["announcement_path"])
    except AnnouncementStorageError:
        logger.warning("Announcement state could not be read safely.")
        announcement_message = ""
        announcement_available = False

    if announcement_form is None:
        announcement_form = AnnouncementForm(
            initial={"announcement_text": announcement_message}
        )

    return render(
        request,
        "dashboard/configuration/announcement.html",
        {
            "announcement": announcement_message,
            "announcement_available": announcement_available,
            "announcement_form": announcement_form,
        },
    )


def update_announcement(request):
    """Replace the operator-managed announcement, then redirect to its page."""

    announcement_form = AnnouncementForm(request.POST)
    if not announcement_form.is_valid():
        return _render_announcement(request, announcement_form)

    announcement_text = announcement_form.cleaned_data["announcement_text"]
    try:
        write_announcement(
            CONFIG["announcement_path"],
            announcement_text,
        )
    except AnnouncementStorageError:
        logger.warning("Announcement update was rejected by safe storage.")
        messages.error(
            request,
            "The announcement could not be saved. Please try again.",
        )
    else:
        if announcement_text:
            messages.success(request, "Announcement updated.")
        else:
            messages.success(request, "Announcement removed.")
    return redirect("announcement")
