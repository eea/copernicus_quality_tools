"""Deprecated compatibility exports for pre-refactor helper imports.

Application code should import from the owning service module directly.
"""

from qc_tool.frontend.dashboard.services.boundaries.presentation import (
    get_boundary_version,
)
from qc_tool.frontend.dashboard.services.configuration.presentation import (
    get_announcement_message,
)
from qc_tool.frontend.dashboard.services.products import find_product_description
from qc_tool.frontend.dashboard.services.products import guess_product_ident


__all__ = (
    "find_product_description",
    "get_announcement_message",
    "get_boundary_version",
    "guess_product_ident",
)
