"""Resolve filename evidence to current, administrator-managed specifications."""

from dataclasses import dataclass, field
import logging
from pathlib import PurePath

from qc_tool.delivery_names import DeliveryName, parse_delivery_name
from qc_tool.frontend.accounts.services.products import available_product_descriptions

from .filename_rules import configured_filename_rules, matches_filename_rules


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProductIdentification:
    status: str
    parsed: DeliveryName
    candidates: tuple[str, ...] = ()
    descriptions: dict[str, str] = field(default_factory=dict)
    message: str = ""

    @property
    def product_ident(self):
        return self.candidates[0] if self.status == "matched" else None


def find_product_description(product_ident):
    descriptions = available_product_descriptions()
    return descriptions.get(product_ident.lower() if product_ident else None, "Unknown")


def _legacy_match(filename, ident, parsed):
    """Preserve known recipe conventions without overriding parsed identity."""

    ident = ident.casefold()
    if parsed.status == "recognized":
        fields = parsed.fields
        if parsed.family == "copernicus:clms:ua-dhm":
            expected = "{}{}_{}".format(
                fields["product"], fields["reference_year"], fields["variable"],
            )
        elif all(fields.get(key) for key in ("programme", "product", "variable", "survey", "type")):
            expected = "_".join(fields[key] for key in ("programme", "product", "variable", "survey"))
            expected += "_" + fields["type"] + fields.get("resolution", "")
        else:
            return False
        # A recognized date, city or broad family prefix cannot select a recipe.
        # Arbitrary identifiers and variants use separate application rules.
        return ident == expected.casefold()
    stem = PurePath(filename).stem.casefold()
    return (
        stem == ident
        or any(stem.startswith(ident + separator) or stem.endswith(separator + ident)
               for separator in ("_", "-", "."))
    )


def identify_delivery(filename):
    """Return deterministic candidates independently of the caller's grants.

    Parsed units are hints only. Neither catalog nor delivery records are written.
    Rules live in application configuration. Specification contents are not read
    or rewritten to perform identification.
    """

    filename = filename.name if isinstance(filename, PurePath) else filename
    automatic = parse_delivery_name(filename)
    parsed = automatic
    candidates = {}
    attempts = {}
    for ident, description in available_product_descriptions().items():
        try:
            rules = configured_filename_rules(ident)
        except ValueError:
            # An invalid explicit rule must never fall back to a filename prefix.
            logger.warning("Invalid filename identification configuration for %s", ident)
            continue
        if rules is not None:
            key = (rules["family"], rules["schema_version"])
            if key not in attempts:
                attempts[key] = parse_delivery_name(
                    filename, family=key[0], schema_version=key[1],
                )
            attempt = attempts[key]
            if attempt.status == "recognized" and parsed.status != "recognized":
                parsed = attempt
            if matches_filename_rules(attempt, rules):
                candidates[ident] = description
                parsed = attempt
        elif automatic.status != "invalid" and _legacy_match(filename, ident, automatic):
            candidates[ident] = description

    ordered = tuple(sorted(candidates))
    if ordered:
        status = "matched" if len(ordered) == 1 else "ambiguous"
        return ProductIdentification(
            status, parsed, ordered, candidates,
            "Choose a matching product specification when starting QC." if len(ordered) > 1 else "",
        )
    if parsed.status == "recognized":
        return ProductIdentification(
            "unconfigured", parsed, message=(
                "The delivery name is recognized, but no matching product specification is available. "
                "Ask an administrator to upload or activate the correct specification."
            ),
        )
    if automatic.status == "invalid":
        return ProductIdentification("invalid", automatic, message=automatic.message)
    return ProductIdentification("unknown", automatic)


def guess_product_ident(delivery_filepath):
    """Compatibility wrapper: only a unique managed match is a product identity."""

    return identify_delivery(delivery_filepath).product_ident


def require_matching_product(filename, product_ident, *, definition=None):
    """Reject conflicting QC selections through the shared job-creation service."""

    result = identify_delivery(filename)
    if result.status in ("invalid", "unconfigured"):
        raise ValueError(result.message)
    if result.candidates and product_ident not in result.candidates:
        raise ValueError("The selected product specification does not match the delivery filename.")
    rules = configured_filename_rules(product_ident)
    if rules is not None:
        parsed = parse_delivery_name(
            filename, family=rules["family"], schema_version=rules["schema_version"],
        )
        if not matches_filename_rules(parsed, rules):
            raise ValueError("The delivery filename does not match the selected product specification.")
    return result


def identification_preview(result, access):
    """Present filename hints without disclosing unassigned catalog records."""

    allowed = tuple(ident for ident in result.candidates if access.can_access_product(ident))
    ident = result.product_ident if result.product_ident in allowed else None
    description = result.descriptions.get(ident, "")
    fields = {
        key: value for key, value in result.parsed.fields.items()
        if key in {"product", "variable", "survey", "representation", "type", "resolution",
                   "area_code", "city", "epsg_code", "version", "revision", "production_date"}
    }
    summary = []
    if description:
        summary.append(description)
    elif result.parsed.status == "recognized":
        summary.append(" ".join(str(fields[key]) for key in ("product", "variable") if fields.get(key)))
    for key in ("survey", "city", "area_code"):
        if fields.get(key):
            summary.append(str(fields[key]))
    return {
        "status": result.status, "parsed_status": result.parsed.status,
        "product_ident": ident, "product_description": description,
        "summary": " · ".join(filter(None, summary)),
        "message": result.message, "fields": fields, "verified": False,
        "family": result.parsed.family, "schema_version": result.parsed.schema_version,
    }
