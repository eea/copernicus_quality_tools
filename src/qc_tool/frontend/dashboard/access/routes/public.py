"""Routes intentionally available without registration or authentication."""

from qc_tool.frontend.dashboard.access.routes.policies import public


PUBLIC_ROUTE_POLICIES = {
    "api_homepage": public("GET"),
    "api_openapi_json": public("GET"),
}
