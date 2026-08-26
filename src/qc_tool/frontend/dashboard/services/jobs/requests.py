"""Validation of API requests that create QC jobs."""

from dataclasses import dataclass
import json

from qc_tool.common import locate_product_definition
from qc_tool.common import QCException
from qc_tool.common import validate_skip_steps
from qc_tool.product_security import normalize_product_ident


class JobRequestError(Exception):
    """A safe, stable job request validation failure."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class JobCreationRequest:
    delivery_id: int
    product_ident: str
    skip_steps: object


@dataclass(frozen=True)
class BatchJobCreationRequest:
    """One bounded browser request that applies the same job to deliveries."""

    delivery_ids: tuple
    product_ident: str
    skip_steps: object


def parse_job_creation_request(payload):
    """Validate identifiers and skippable steps against one definition."""

    if not isinstance(payload, dict):
        raise _invalid_request()
    delivery_id = positive_identifier(payload.get("delivery_id"), "delivery_id")
    requested_product = normalize_product_ident(payload.get("product_ident"))
    if requested_product is None:
        raise JobRequestError(
            "invalid_product_ident",
            "Select an available product definition.",
        )

    try:
        definition_path = locate_product_definition(requested_product)
        definition = json.loads(definition_path.read_text(encoding="utf-8"))
        if not isinstance(definition, dict) or not isinstance(
            definition.get("steps"),
            list,
        ):
            raise ValueError
    except (OSError, UnicodeError, ValueError, QCException, json.JSONDecodeError):
        raise JobRequestError(
            "product_definition_unavailable",
            "The selected product definition is unavailable.",
        ) from None

    skip_steps_text, skip_step_numbers = _parse_skip_steps(
        payload.get("skip_steps")
    )
    try:
        validate_skip_steps(skip_step_numbers, definition)
    except (KeyError, TypeError, QCException) as exc:
        message = (
            str(exc)
            if isinstance(exc, QCException)
            else "The selected product definition is invalid."
        )
        raise JobRequestError("invalid_skip_steps", message) from None
    return JobCreationRequest(
        delivery_id=delivery_id,
        product_ident=requested_product,
        skip_steps=skip_steps_text,
    )


def parse_batch_job_creation_request(payload, *, maximum_deliveries=100):
    """Validate the browser form without partially creating QC jobs."""

    if (
        isinstance(maximum_deliveries, bool)
        or not isinstance(maximum_deliveries, int)
        or maximum_deliveries <= 0
    ):
        raise ValueError("maximum_deliveries must be a positive integer")
    delivery_ids_value = _single_form_value(payload, "delivery_ids")
    product_ident = _single_form_value(payload, "product_ident")
    skip_steps = _single_form_value(payload, "skip_steps", required=False)
    if (
        not isinstance(delivery_ids_value, str)
        or not delivery_ids_value
        or delivery_ids_value != delivery_ids_value.strip()
    ):
        raise JobRequestError(
            "invalid_delivery_ids",
            "Select at least one delivery.",
        )
    raw_ids = delivery_ids_value.split(",")
    if len(raw_ids) > maximum_deliveries:
        raise JobRequestError(
            "too_many_deliveries",
            "Too many deliveries were selected at once.",
        )
    delivery_ids = tuple(
        positive_identifier(value, "delivery_id") for value in raw_ids
    )
    if len(set(delivery_ids)) != len(delivery_ids):
        raise JobRequestError(
            "duplicate_delivery_ids",
            "A delivery may be selected only once.",
        )

    validated = parse_job_creation_request(
        {
            "delivery_id": delivery_ids[0],
            "product_ident": product_ident,
            "skip_steps": skip_steps,
        }
    )
    return BatchJobCreationRequest(
        delivery_ids=delivery_ids,
        product_ident=validated.product_ident,
        skip_steps=validated.skip_steps,
    )


def positive_identifier(value, field_name):
    """Parse one positive database identifier without accepting booleans."""

    if isinstance(value, bool):
        raise JobRequestError(
            "invalid_{}".format(field_name),
            "{} must be a positive integer.".format(field_name),
        )
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise JobRequestError(
            "invalid_{}".format(field_name),
            "{} must be a positive integer.".format(field_name),
        ) from None
    if parsed <= 0 or str(parsed) != str(value):
        raise JobRequestError(
            "invalid_{}".format(field_name),
            "{} must be a positive integer.".format(field_name),
        )
    return parsed


def _parse_skip_steps(value):
    if value in (None, ""):
        return None, []
    if (
        not isinstance(value, str)
        or len(value) > 100
        or any(not part.isdigit() for part in value.split(","))
    ):
        raise JobRequestError(
            "invalid_skip_steps",
            "skip_steps must be a comma-separated list of step numbers.",
        )
    numbers = [int(part) for part in value.split(",")]
    return ",".join(str(number) for number in numbers), numbers


def _invalid_request():
    return JobRequestError("invalid_job_request", "The job request is invalid.")


def _single_form_value(payload, name, *, required=True):
    getlist = getattr(payload, "getlist", None)
    if callable(getlist):
        values = getlist(name)
        if len(values) > 1 or (required and len(values) != 1):
            raise _invalid_request()
        return values[0] if values else None
    try:
        value = payload.get(name)
    except AttributeError:
        raise _invalid_request()
    if required and value is None:
        raise _invalid_request()
    return value
