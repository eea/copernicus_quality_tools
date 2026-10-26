"""Safe announcement presentation values for workspace pages."""

import logging
from qc_tool.common import CONFIG
from qc_tool.frontend.dashboard.services.configuration import AnnouncementStorageError
from qc_tool.frontend.dashboard.services.configuration import read_announcement

logger = logging.getLogger(__name__)


def announcement_context():
    """Read one announcement consistently for full pages and compact notices."""
    try:
        message = read_announcement(CONFIG["announcement_path"])
    except AnnouncementStorageError:
        logger.warning("Announcement state could not be read safely.")
        return {"announcement": "", "announcement_available": False}
    return {"announcement": message, "announcement_available": True}


def get_announcement_message():
    """Compact notices omit empty and unavailable messages."""
    return announcement_context()["announcement"] or None
