"""Safe persistence for administrator-managed dashboard configuration."""

from .announcements import AnnouncementStorageError
from .announcements import MAX_ANNOUNCEMENT_BYTES
from .announcements import read_announcement
from .announcements import write_announcement


__all__ = (
    "AnnouncementStorageError",
    "MAX_ANNOUNCEMENT_BYTES",
    "read_announcement",
    "write_announcement",
)
