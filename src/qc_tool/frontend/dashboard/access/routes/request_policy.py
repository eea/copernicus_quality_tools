"""Resolve the validated dashboard route policy for the current request."""

from qc_tool.frontend.dashboard.access.routes.policies import RoutePolicy


def policy_for_request(request):
    """Return the resolved :class:`RoutePolicy`, if this is a known route."""

    resolver_match = getattr(request, "resolver_match", None)
    policy = getattr(
        getattr(resolver_match, "func", None),
        "_qc_tool_route_policy",
        None,
    )
    return policy if isinstance(policy, RoutePolicy) else None
