"""Validate QC Tool filename routing without consulting specification contents."""

import re

from django.conf import settings

from qc_tool.delivery_names import DeliveryNameParserUnavailable
from qc_tool.delivery_names import describe_delivery_schema


def configured_filename_rules(product_ident):
    """Return optional application rules for a current managed identifier."""

    configured = settings.DELIVERY_FILENAME_RULES
    if not isinstance(configured, dict):
        raise DeliveryNameParserUnavailable("Delivery filename recognition configuration is unavailable.")
    if product_ident not in configured:
        return None
    return validate_filename_rules(configured[product_ident])


def validate_filename_rules(rules):
    """Return validated rules; never interpret paths or executable code."""

    if not isinstance(rules, dict) or set(rules) != {"family", "schema_version", "match"}:
        raise ValueError("Filename identification requires family, schema_version and match.")
    family = rules["family"]
    version = rules["schema_version"]
    if not isinstance(family, str) or not isinstance(version, str) or not family or not version:
        raise ValueError("Choose an installed parsEO family and an explicit schema version.")
    schema = describe_delivery_schema(family, version)
    matches = rules["match"]
    if not isinstance(matches, dict) or not matches or len(matches) > 32:
        raise ValueError("Filename identification match must contain field/value pairs.")
    fields = schema["fields"]
    for field, value in matches.items():
        if (
            field not in fields or not isinstance(value, str)
            or not value or value != value.strip() or len(value) > 255
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError("Filename identification contains an unknown field or invalid value.")
        specification = fields[field]
        enums = specification.get("enum")
        pattern = specification.get("pattern")
        if enums and not any(isinstance(choice, str) and choice.casefold() == value.casefold() for choice in enums):
            raise ValueError("Filename identification value does not match the schema field '{}'.".format(field))
        if pattern and re.fullmatch(pattern, value, flags=re.IGNORECASE) is None:
            raise ValueError("Filename identification value does not match the schema field '{}'.".format(field))
    return {
        "family": schema["schema_id"],
        "schema_version": schema["schema_version"],
        "match": dict(matches),
    }


def matches_filename_rules(parsed, rules):
    return parsed.status == "recognized" and all(
        isinstance(parsed.fields.get(field), str)
        and parsed.fields[field].casefold() == expected.casefold()
        for field, expected in rules["match"].items()
    )
