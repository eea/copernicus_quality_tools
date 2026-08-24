"""Fail-closed access contracts for dashboard routes.

Visibility answers one question only: may an unregistered visitor use the
route? Authentication, authorization, HTTP methods, and denial formatting are
independent details of a private route.
"""

from dataclasses import dataclass
from enum import Enum

from django.views.decorators.http import require_http_methods

from qc_tool.frontend.accounts.authentication.decorators import api_key_required
from qc_tool.frontend.accounts.authorization.decorators import (
    account_json_permission_required,
    account_permission_required,
)
from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.dashboard.authentication import worker_token_required


class RouteVisibility(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"


class AuthenticationMode(str, Enum):
    NONE = "none"
    SESSION = "session"
    API_KEY = "api_key"
    WORKER_TOKEN = "worker_token"


class DenialResponse(str, Enum):
    LOGIN_REDIRECT = "login_redirect"
    JSON = "json"
    STATUS_ONLY = "status_only"


@dataclass(frozen=True)
class RoutePolicy:
    visibility: RouteVisibility
    authentication: AuthenticationMode
    methods: tuple[str, ...]
    permission: AccountPermission | None = None
    denial_response: DenialResponse | None = None

    def __post_init__(self):
        if not self.methods:
            raise ValueError("Every route must declare at least one HTTP method.")
        if any(method != method.upper() for method in self.methods):
            raise ValueError("Route methods must use uppercase HTTP verbs.")
        if len(set(self.methods)) != len(self.methods):
            raise ValueError("Route methods cannot contain duplicates.")

        if self.visibility is RouteVisibility.PUBLIC:
            if self.authentication is not AuthenticationMode.NONE:
                raise ValueError("Public routes cannot require authentication.")
            if self.permission is not None:
                raise ValueError("Public routes cannot require a permission.")
            if self.denial_response is not None:
                raise ValueError("Public routes cannot define a denial response.")
            return

        if self.visibility is not RouteVisibility.PRIVATE:
            raise ValueError(f"Unsupported route visibility: {self.visibility!r}")
        if self.authentication is AuthenticationMode.NONE:
            raise ValueError("Private routes must require authentication.")
        if self.denial_response is None:
            raise ValueError("Private routes must define a denial response.")

        if self.authentication in {
            AuthenticationMode.SESSION,
            AuthenticationMode.API_KEY,
        }:
            if self.permission is None:
                raise ValueError(
                    "Private account routes must require a Django permission."
                )
        elif self.authentication is AuthenticationMode.WORKER_TOKEN:
            if self.permission is not None:
                raise ValueError(
                    "Worker-token routes cannot require an account permission."
                )
        else:
            raise ValueError(
                f"Unsupported private authentication mode: {self.authentication!r}"
            )

        allowed_denials = {
            AuthenticationMode.SESSION: {
                DenialResponse.LOGIN_REDIRECT,
                DenialResponse.JSON,
            },
            AuthenticationMode.API_KEY: {DenialResponse.JSON},
            AuthenticationMode.WORKER_TOKEN: {DenialResponse.STATUS_ONLY},
        }
        if self.denial_response not in allowed_denials[self.authentication]:
            raise ValueError(
                f"{self.authentication.value} routes cannot use "
                f"{self.denial_response.value} denial responses."
            )


def public(*methods):
    return RoutePolicy(
        visibility=RouteVisibility.PUBLIC,
        authentication=AuthenticationMode.NONE,
        methods=methods,
    )


def private_session_page(permission, *methods):
    return RoutePolicy(
        visibility=RouteVisibility.PRIVATE,
        authentication=AuthenticationMode.SESSION,
        methods=methods,
        permission=AccountPermission(permission),
        denial_response=DenialResponse.LOGIN_REDIRECT,
    )


def private_session_data(permission, *methods):
    return RoutePolicy(
        visibility=RouteVisibility.PRIVATE,
        authentication=AuthenticationMode.SESSION,
        methods=methods,
        permission=AccountPermission(permission),
        denial_response=DenialResponse.JSON,
    )


def private_api_key(permission, *methods):
    return RoutePolicy(
        visibility=RouteVisibility.PRIVATE,
        authentication=AuthenticationMode.API_KEY,
        methods=methods,
        permission=AccountPermission(permission),
        denial_response=DenialResponse.JSON,
    )


def private_worker(*methods):
    return RoutePolicy(
        visibility=RouteVisibility.PRIVATE,
        authentication=AuthenticationMode.WORKER_TOKEN,
        methods=methods,
        denial_response=DenialResponse.STATUS_ONLY,
    )


def _apply_private_policy(policy, method_limited_view):
    if policy.authentication is AuthenticationMode.SESSION:
        if policy.denial_response is DenialResponse.LOGIN_REDIRECT:
            return account_permission_required(policy.permission)(
                method_limited_view
            )
        if policy.denial_response is DenialResponse.JSON:
            return account_json_permission_required(policy.permission)(
                method_limited_view
            )
        raise RuntimeError("Unsupported session denial response.")

    if policy.authentication is AuthenticationMode.API_KEY:
        if policy.denial_response is not DenialResponse.JSON:
            raise RuntimeError("API-key routes must use JSON denial responses.")
        return api_key_required(permission=policy.permission)(method_limited_view)

    if policy.authentication is AuthenticationMode.WORKER_TOKEN:
        if policy.denial_response is not DenialResponse.STATUS_ONLY:
            raise RuntimeError("Worker routes must use status-only denials.")
        return worker_token_required(method_limited_view)

    raise RuntimeError(
        f"Unsupported private authentication mode: {policy.authentication!r}"
    )


def apply_route_policy(policy, view_func):
    """Apply a validated route contract before the callback may run."""

    method_limited_view = require_http_methods(policy.methods)(view_func)

    if policy.visibility is RouteVisibility.PUBLIC:
        protected_view = method_limited_view
    elif policy.visibility is RouteVisibility.PRIVATE:
        protected_view = _apply_private_policy(policy, method_limited_view)
    else:
        raise RuntimeError(f"Unsupported route visibility: {policy.visibility!r}")

    protected_view._qc_tool_route_policy = policy
    return protected_view
