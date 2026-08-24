"""Canonical validation for job identifiers.

Job identifiers cross Django, JSON, filesystem, process, and database
boundaries.  Django's UUID converters and model fields return
``uuid.UUID`` objects, while worker protocols use strings.  Normalizing both
representations here keeps every consumer on the same fixed, safe alphabet.
"""

from uuid import UUID


class JobIdentifierError(ValueError):
    """A job identifier is malformed or unsafe for local use."""


def normalize_job_uuid(value):
    """Return a canonical UUID string for a UUID object or ASCII UUID text."""

    if isinstance(value, UUID):
        return str(value)
    if not isinstance(value, str) or not value.isascii():
        raise JobIdentifierError("job UUID is invalid")
    try:
        return str(UUID(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise JobIdentifierError("job UUID is invalid") from exc


def compact_job_uuid(value):
    """Return the 32-character lowercase UUID used in job directory names."""

    return normalize_job_uuid(value).replace("-", "")
