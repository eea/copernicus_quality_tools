"""Duplicate-AOI detection, authorization, and manager resolution."""

from .access import can_resolve_product_aoi
from .reconciliation import reconcile_published_submission
from .resolution import resolve_submission_conflict

__all__ = (
    "can_resolve_product_aoi",
    "reconcile_published_submission",
    "resolve_submission_conflict",
)
