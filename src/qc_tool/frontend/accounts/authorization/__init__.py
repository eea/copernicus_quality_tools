"""Role resolution and account-level access policy."""

from qc_tool.frontend.accounts.authorization.access import AccountAccess
from qc_tool.frontend.accounts.authorization.access import access_for
from qc_tool.frontend.accounts.authorization.access import access_for_request
from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.accounts.authorization.roles import Role

__all__ = [
    "AccountAccess",
    "AccountPermission",
    "Role",
    "access_for",
    "access_for_request",
]
