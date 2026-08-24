"""Explicit resource limits for untrusted delivery archives."""

from dataclasses import dataclass
import math
import os


@dataclass(frozen=True)
class ArchiveLimits:
    max_archive_bytes: int = 50 * 1024 * 1024 * 1024
    max_members: int = 25_000
    max_member_bytes: int = 50 * 1024 * 1024 * 1024
    max_uncompressed_bytes: int = 100 * 1024 * 1024 * 1024
    max_compression_ratio: float = 100.0
    max_path_bytes: int = 1_024
    max_component_bytes: int = 255
    max_path_depth: int = 32

    def __post_init__(self):
        integer_fields = (
            "max_archive_bytes",
            "max_members",
            "max_member_bytes",
            "max_uncompressed_bytes",
            "max_path_bytes",
            "max_component_bytes",
            "max_path_depth",
        )
        for field_name in integer_fields:
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError("archive limits must be positive integers")
        ratio = self.max_compression_ratio
        if (
            isinstance(ratio, bool)
            or not isinstance(ratio, (int, float))
            or not math.isfinite(ratio)
            or ratio < 1
        ):
            raise ValueError("archive compression ratio must be finite and >= 1")

    @classmethod
    def from_environment(cls, prefix="DELIVERY_ARCHIVE_"):
        """Load optional worker limits while retaining reviewed defaults."""

        defaults = cls()
        values = {}
        integer_names = (
            "max_archive_bytes",
            "max_members",
            "max_member_bytes",
            "max_uncompressed_bytes",
            "max_path_bytes",
            "max_component_bytes",
            "max_path_depth",
        )
        for field_name in integer_names:
            variable = prefix + field_name.upper()
            raw_value = os.environ.get(variable)
            values[field_name] = (
                getattr(defaults, field_name)
                if raw_value is None
                else _positive_integer(raw_value, variable)
            )
        ratio_variable = prefix + "MAX_COMPRESSION_RATIO"
        raw_ratio = os.environ.get(ratio_variable)
        try:
            values["max_compression_ratio"] = (
                defaults.max_compression_ratio
                if raw_ratio is None
                else float(raw_ratio)
            )
        except ValueError as exc:
            raise ValueError("{} must be numeric".format(ratio_variable)) from exc
        return cls(**values)


def _positive_integer(value, variable):
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("{} must be an integer".format(variable)) from exc
    if parsed <= 0:
        raise ValueError("{} must be positive".format(variable))
    return parsed
