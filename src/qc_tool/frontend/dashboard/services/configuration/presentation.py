"""Safe announcement presentation values for workspace pages."""

import logging
from qc_tool.common import CONFIG
from qc_tool.frontend.dashboard.services.configuration import AnnouncementStorageError
from qc_tool.frontend.dashboard.services.configuration import read_announcement

logger = logging.getLogger(__name__)


def get_announcement_message():
    """
    Reads announcement message from the announcement.txt file.
    """
    try:
        return read_announcement(CONFIG["announcement_path"]) or None
    except AnnouncementStorageError:
        logger.warning("Announcement state could not be read safely.")
        return None
