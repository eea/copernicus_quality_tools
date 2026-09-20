"""Bounded filename observations from explicitly versioned parsEO schemas.

This module has no catalog or authorization behavior. A parsed area code is a
filename hint, never a QC-verified product unit or permission grant.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
import re
import unicodedata


MAX_FILENAME_BYTES = 255
_SCHEMA_VERSION = re.compile(r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}\Z")
_SCHEMA_FAMILY = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9:-]{0,127}\Z")
_UA_VERSION = "0.0.0"
_UA_FAMILIES = {
    "LCU": "copernicus:clms:ua-lcu", "LCUC": "copernicus:clms:ua-lcu",
    "BBH": "copernicus:clms:ua-lcu", "GUA": "copernicus:clms:ua-lcu",
    "STL": "copernicus:clms:ua-stl", "DHM": "copernicus:clms:ua-dhm",
}
_UPPERCASE_TOKENS = frozenset(("programme", "product", "variable", "survey", "type", "version", "revision"))


class DeliveryNameParserUnavailable(RuntimeError):
    """The installed parser or its reviewed schema resources are unavailable."""


@dataclass(frozen=True)
class DeliveryName:
    status: str
    filename: str
    fields: dict = field(default_factory=dict)
    family: str | None = None
    schema_version: str | None = None
    message: str = ""


def describe_delivery_schema(family, schema_version):
    """Describe an installed, explicit schema version without accepting paths.

    Invalid configuration raises ``ValueError``. A missing dependency fails
    explicitly instead of making recognizable names look unsupported. Returned
    metadata is a copy, so configuration validation cannot mutate cached schemas.
    """

    if not isinstance(family, str) or not _SCHEMA_FAMILY.fullmatch(family):
        raise ValueError("Use a packaged parsEO schema family identifier.")
    if not isinstance(schema_version, str) or not _SCHEMA_VERSION.fullmatch(schema_version):
        raise ValueError("Choose an explicit parsEO schema version such as 0.0.0.")
    return deepcopy(_describe_schema(family.casefold(), schema_version))


@lru_cache(maxsize=64)
def _describe_schema(family, schema_version):
    try:
        from parseo.parser import describe_schema
    except ImportError as exc:
        raise DeliveryNameParserUnavailable("Delivery filename recognition is unavailable.") from exc
    try:
        schema = describe_schema(family, version=schema_version)
    except KeyError as exc:
        raise ValueError("The configured parsEO schema family or version is not installed.") from exc
    except (OSError, RuntimeError) as exc:
        raise DeliveryNameParserUnavailable("Delivery filename recognition is unavailable.") from exc
    canonical = schema.get("schema_id")
    if not isinstance(canonical, str) or schema.get("schema_version") != schema_version:
        raise DeliveryNameParserUnavailable("Delivery filename recognition is unavailable.")
    # parsEO permits full schema IDs by taking their final component. Do not
    # accept a fabricated namespace that happens to end in a packaged family.
    if ":" in family and canonical.casefold() != family:
        raise ValueError("The configured parsEO schema family is not installed.")
    return schema


def parse_delivery_name(filename, *, family=None, schema_version=None):
    """Classify a safe basename using one pinned naming schema.

    Urban Atlas is recognized automatically. Other families require an explicit
    family and version from QC Tool's application configuration. Only a final ZIP
    extension is removed as an archive wrapper; the original basename is kept.
    """

    if not _safe_basename(filename):
        return DeliveryName("invalid", filename if isinstance(filename, str) else "", message="Use a filename of at most 255 UTF-8 bytes without paths or control characters.")
    name = filename[:-4] if filename.casefold().endswith(".zip") else filename
    if not name:
        return DeliveryName("invalid", filename, message="The delivery filename is empty.")
    if family is None and schema_version is None:
        family, schema_version, recognized_prefix = _automatic_schema(name)
        if family is None:
            return DeliveryName(
                "invalid" if recognized_prefix else "unsupported", filename,
                message="The Urban Atlas filename has an unsupported or missing product type." if recognized_prefix else "This filename does not use an automatically recognized naming convention.",
            )
    elif family is None or schema_version is None:
        return DeliveryName("invalid", filename, message="Filename recognition requires both a schema family and an explicit schema version.")
    try:
        schema = describe_delivery_schema(family, schema_version)
    except ValueError as exc:
        return DeliveryName("invalid", filename, message=str(exc))
    canonical_family = schema["schema_id"]
    if re.search(r"\s+\([0-9]+\)(?:\.[A-Za-z0-9]+)?\Z", name):
        return DeliveryName(
            "invalid", filename, family=canonical_family, schema_version=schema_version,
            message="The filename contains a copy suffix such as (1). Use the original delivery filename and upload it again.",
        )
    try:
        from parseo.parser import ParseError, parse
    except ImportError as exc:
        raise DeliveryNameParserUnavailable("Delivery filename recognition is unavailable.") from exc
    try:
        parsed = parse(name, family=canonical_family, version=schema_version, ignore_case=True)
    except ParseError as exc:
        # No raw schema paths, regex internals or guessed corrections in the UI.
        field_name = exc.field.replace("_", " ") if isinstance(exc.field, str) else "filename"
        return DeliveryName("invalid", filename, family=canonical_family, schema_version=schema_version, message=f"The delivery {field_name} does not match the configured naming convention.")
    except (OSError, KeyError, RuntimeError) as exc:
        raise DeliveryNameParserUnavailable("Delivery filename recognition is unavailable.") from exc
    fields = _canonical_fields(parsed.fields, schema["fields"])
    invalid_date = _invalid_date(fields)
    if invalid_date:
        return DeliveryName("invalid", filename, family=canonical_family, schema_version=schema_version, message=invalid_date)
    return DeliveryName("recognized", filename, fields=fields, family=canonical_family, schema_version=schema_version)


def _safe_basename(filename):
    if not isinstance(filename, str) or not filename or filename in (".", ".."):
        return False
    if any(character in filename for character in ("/", "\\", ":")):
        return False
    if any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in filename):
        return False
    return len(filename.encode("utf-8")) <= MAX_FILENAME_BYTES


def _automatic_schema(name):
    upper = name.upper()
    if upper.startswith("CLMS_UA_"):
        tokens = upper.split("_", 3)
        subtype = tokens[2] if len(tokens) > 2 else ""
        if subtype == "PDF":
            # QC Tool has an administrator-managed UA PDF recipe, but this
            # parsEO snapshot has no corresponding document-package schema.
            # Preserve its existing catalog-prefix/manual selection workflow.
            return None, None, False
        return _UA_FAMILIES.get(subtype), _UA_VERSION, True
    # The pinned DHM schema precedes the CLMS prefix convention. Recognize only
    # its distinctive UA<year>_DHM suffix rather than guessing other legacy UA.
    if re.search(r"_UA[0-9]{4}_DHM(?:\.[^.]+)?\Z", upper):
        return "copernicus:clms:ua-dhm", _UA_VERSION, True
    return None, None, False


def _canonical_fields(parsed_fields, schema_fields):
    fields = dict(parsed_fields)
    for key, value in fields.items():
        if not isinstance(value, str):
            continue
        enums = schema_fields.get(key, {}).get("enum", ())
        canonical = next((choice for choice in enums if isinstance(choice, str) and choice.casefold() == value.casefold()), None)
        if canonical is not None:
            fields[key] = canonical
        elif key in _UPPERCASE_TOKENS:
            fields[key] = value.upper()
        elif key in ("resolution", "extension"):
            fields[key] = value.casefold()
    # parsEO's schema mappings use exact token keys even with ignore_case=True.
    # Derive the display hint from the validated, canonical representation token.
    representation = {"V": "vector", "VEC": "vector", "R": "raster"}.get(fields.get("type"))
    if representation is not None:
        fields["representation"] = representation
    return fields


def _invalid_date(fields):
    production_date = fields.get("production_date")
    if production_date:
        try:
            if not re.fullmatch(r"[0-9]{8}", production_date):
                raise ValueError
            date(int(production_date[:4]), int(production_date[4:6]), int(production_date[6:]))
        except (TypeError, ValueError):
            return "The production date must be a valid calendar date in YYYYMMDD format."
    survey = fields.get("survey", "")
    if re.fullmatch(r"C[0-9]{4}-[0-9]{4}", survey):
        first, last = int(survey[1:5]), int(survey[6:])
        if first < 1 or first >= last:
            return "The survey period must end after its starting year."
    elif re.fullmatch(r"S[0-9]{4}", survey) and int(survey[1:]) < 1:
        return "The survey year must be a valid calendar year."
    reference_year = fields.get("reference_year")
    if isinstance(reference_year, str) and re.fullmatch(r"[0-9]{4}", reference_year) and int(reference_year) < 1:
        return "The reference year must be a valid calendar year."
    return None
