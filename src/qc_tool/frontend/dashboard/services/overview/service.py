"""Compatibility entry point for workspace overview construction.

Callers should normally import from :mod:`qc_tool.frontend.dashboard.services.overview`.
Keeping this thin module protects older imports while the implementation lives
in focused section builders.
"""

from .workspace import DEFAULT_ITEM_LIMIT
from .workspace import build_workspace_overview


__all__ = ("DEFAULT_ITEM_LIMIT", "build_workspace_overview")
