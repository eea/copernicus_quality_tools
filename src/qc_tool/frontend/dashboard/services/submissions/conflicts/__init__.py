"""Duplicate-product unit detection, authorization, and manager resolution."""

from .access import can_resolve_product_unit
from .reconciliation import reconcile_published_submission
from .resolution import resolve_submission_conflict

__all__ = (
    "can_resolve_product_unit",
    "reconcile_published_submission",
    "resolve_submission_conflict",
)
