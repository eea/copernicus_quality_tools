from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from qc_tool.frontend.accounts.authorization.access import access_for_request
from qc_tool.frontend.accounts.authorization.permissions import AccountPermission


def account_permission_required(permission):
    """Require login and one explicit QC Tool application permission."""

    permission = AccountPermission(permission)

    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not access_for_request(request).allows(permission):
                raise PermissionDenied(
                    "Your account is not permitted to perform this action."
                )
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


def administrator_required(view_func):
    return account_permission_required(
        AccountPermission.MANAGE_CONFIGURATION
    )(view_func)
