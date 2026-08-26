"""Django-admin registrations for submission candidates and conflicts."""

from .candidates import DeliverySubmissionAdmin
from .conflicts import SubmissionConflictAdmin
from .conflicts import SubmissionConflictEventAdmin


__all__ = (
    "DeliverySubmissionAdmin",
    "SubmissionConflictAdmin",
    "SubmissionConflictEventAdmin",
)
