"""Small value objects for merging AOI metadata across QC job steps."""

from dataclasses import dataclass
from typing import Optional

from .identifiers import aoi_codes_equivalent
from .identifiers import normalize_aoi_code


@dataclass(frozen=True)
class AoiMetadata:
    """The canonical AOI state after merging one additional observation."""

    value: Optional[str]
    conflicted: bool = False


def merge_aoi_metadata(previous, candidate, *, already_conflicted=False):
    """Merge job-step AOI observations without altering the QC result.

    A conflict makes AOI metadata unavailable for the remainder of the job.
    It is a metadata integrity issue, not by itself a reason to overwrite the
    outcome chosen by the product's existing QC checks.
    """

    if already_conflicted:
        return AoiMetadata(None, conflicted=True)

    previous_code = normalize_aoi_code(previous)
    candidate_code = normalize_aoi_code(candidate)
    if candidate_code is None:
        return AoiMetadata(
            None,
            conflicted=previous_code is not None,
        )
    if previous_code is None:
        return AoiMetadata(candidate_code)
    if not aoi_codes_equivalent(previous_code, candidate_code):
        return AoiMetadata(None, conflicted=True)
    return AoiMetadata(previous_code)
