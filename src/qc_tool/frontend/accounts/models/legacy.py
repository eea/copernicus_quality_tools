"""Stable imports for account models retaining dashboard model identities.

Moving deployed Django models between apps also moves content types and
permissions, so that change belongs in a dedicated data-preserving migration.
"""

from qc_tool.frontend.dashboard.models import ApiUser
from qc_tool.frontend.dashboard.models import UserProfile

__all__ = ["ApiUser", "UserProfile"]
