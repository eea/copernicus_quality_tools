"""Validation for identifiers crossing the worker process boundary.

The scheduler normally supplies values already checked by the pull protocol,
but the worker command can also be invoked directly.  Keeping the validation
here gives both entry points the same rules before a value reaches a path or a
PostgreSQL identifier.
"""

from pathlib import Path
import unicodedata

from qc_tool.jobs import compact_job_uuid
from qc_tool.jobs import JobIdentifierError
from qc_tool.jobs import normalize_job_uuid


def job_schema_name(value):
    """Return the fixed-alphabet PostgreSQL schema name for a job UUID."""

    return "job_{}".format(compact_job_uuid(value))


def validate_path_component(value, maximum_length, field_name):
    """Validate one opaque filename component without normalizing it.

    User and delivery names are persisted identifiers.  Silently changing
    Unicode or case would risk addressing another user's data, so unsafe or
    non-canonical values are rejected instead.
    """

    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum_length
        or len(value.encode("utf-8")) > 255
        or not value.isprintable()
        or value in {".", ".."}
        or Path(value).name != value
        or "\\" in value
        or value != unicodedata.normalize("NFC", value)
        or any(
            unicodedata.category(character) in {"Cc", "Cf"}
            for character in value
        )
    ):
        raise JobIdentifierError("{} is invalid".format(field_name))
    return value
