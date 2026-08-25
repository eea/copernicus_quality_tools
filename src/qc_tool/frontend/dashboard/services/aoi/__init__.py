"""Django persistence services for canonical AOI job metadata."""

from .artifacts import load_aoi_result_document
from .backfill import AoiBackfillResult
from .backfill import backfill_aoi_metadata
from .contracts import AoiResultUpdate
from .contracts import AoiUpdateAction
from .errors import AoiResultUnavailable
from .lifecycle import create_delivery_job
from .lifecycle import refresh_delivery_projection
from .lifecycle import update_job_status
from .results import aoi_update_from_result
from .results import apply_result_aoi


__all__ = (
    "AoiResultUpdate",
    "AoiResultUnavailable",
    "AoiUpdateAction",
    "AoiBackfillResult",
    "aoi_update_from_result",
    "apply_result_aoi",
    "backfill_aoi_metadata",
    "create_delivery_job",
    "load_aoi_result_document",
    "refresh_delivery_projection",
    "update_job_status",
)
