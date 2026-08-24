"""Central public/private access registry for every dashboard URL."""

from qc_tool.frontend.dashboard.access.routes.policies import apply_route_policy
from qc_tool.frontend.dashboard.access.routes.private import PRIVATE_ROUTE_POLICIES
from qc_tool.frontend.dashboard.access.routes.public import PUBLIC_ROUTE_POLICIES


_duplicates = set(PUBLIC_ROUTE_POLICIES) & set(PRIVATE_ROUTE_POLICIES)
if _duplicates:
    raise RuntimeError(
        f"Routes cannot be both public and private: {sorted(_duplicates)}"
    )

ROUTE_POLICIES = {
    **PUBLIC_ROUTE_POLICIES,
    **PRIVATE_ROUTE_POLICIES,
}


def protect_dashboard_route(route_name, view_func):
    """Apply the required access contract to one named dashboard route."""

    try:
        policy = ROUTE_POLICIES[route_name]
    except KeyError as error:
        raise RuntimeError(
            f"Dashboard route {route_name!r} has no declared access policy."
        ) from error
    return apply_route_policy(policy, view_func)


__all__ = [
    "PRIVATE_ROUTE_POLICIES",
    "PUBLIC_ROUTE_POLICIES",
    "ROUTE_POLICIES",
    "protect_dashboard_route",
]
