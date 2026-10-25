"""Read-only workspace announcements and their shared presentation state."""

import logging
from django.shortcuts import render
from qc_tool.common import CONFIG
from qc_tool.frontend.dashboard.services.configuration import AnnouncementStorageError
from qc_tool.frontend.dashboard.services.configuration import read_announcement

logger = logging.getLogger(__name__)


def announcement(request):
    """Render the current announcement for an authenticated QC Tool user."""

    return render(
        request, "dashboard/configuration/announcement.html", announcement_context(),
    )


def announcement_context():
    """Read one current message for the workspace and Admin preview."""

    announcement_available = True
    try:
        announcement_message = read_announcement(CONFIG["announcement_path"])
    except AnnouncementStorageError:
        logger.warning("Announcement state could not be read safely.")
        announcement_message = ""
        announcement_available = False

    return {
        "announcement": announcement_message,
        "announcement_available": announcement_available,
    }
