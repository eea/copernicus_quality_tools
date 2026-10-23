"""Deployment settings adapter for boundary-package resource limits.

The archive service remains independent of Django settings: HTTP callers obtain
one validated limit object here and pass it explicitly to the service.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .contracts import BoundaryPackageLimits
from .errors import BoundaryPackageConfigurationError


SETTING_NAME = "QC_TOOL_BOUNDARY_PACKAGE_LIMITS"
_ENVIRONMENT_NAMES = {
    name: f"QC_TOOL_BOUNDARY_{name.upper()}"
    for name in BoundaryPackageLimits.__dataclass_fields__
}


def boundary_package_limits_from_environment(
    environment: Mapping[str, str],
) -> dict[str, int | float]:
    """Build Django's limit mapping, refusing invalid deployment values.

    Defaults are defined only by ``BoundaryPackageLimits``. Invalid environment
    overrides fail settings loading rather than silently reverting to defaults.
    """

    values: dict[str, int | float] = {}
    for field_name, variable_name in _ENVIRONMENT_NAMES.items():
        if variable_name not in environment:
            continue
        raw_value = environment[variable_name]
        try:
            if not isinstance(raw_value, str):
                raise ValueError("environment values must be text")
            value = (
                float(raw_value)
                if field_name == "max_compression_ratio"
                else int(raw_value)
            )
            # Validate each override through the same domain contract, while
            # retaining the operator-facing environment variable in the error.
            BoundaryPackageLimits.from_mapping({field_name: value})
        except (TypeError, ValueError, OverflowError) as exc:
            expected = (
                "a finite number of at least 1"
                if field_name == "max_compression_ratio"
                else "a positive integer"
            )
            raise ImproperlyConfigured(
                f"{variable_name} must be {expected}"
            ) from exc
        values[field_name] = value
    return asdict(BoundaryPackageLimits.from_mapping(values))


def get_boundary_package_limits() -> BoundaryPackageLimits:
    """Return current, validated deployment limits without caching settings.

    Direct Django setting overrides use typed values rather than environment
    strings. A dedicated setting with unknown keys is refused so a misspelled
    safety limit cannot silently select a different default.
    """

    values = getattr(settings, SETTING_NAME, {})
    try:
        if not isinstance(values, Mapping):
            raise ValueError("must be a mapping")
        unknown = set(values).difference(_ENVIRONMENT_NAMES)
        if unknown:
            raise ValueError("contains unsupported limit names")
        return BoundaryPackageLimits.from_mapping(values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise BoundaryPackageConfigurationError(
            f"{SETTING_NAME}: {exc}"
        ) from exc
