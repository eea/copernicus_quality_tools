from django.urls import path

from qc_tool.frontend.dashboard.access.routes import protect_dashboard_route


def protected_path(route, view, *, name):
    """Register a callback using its required route access contract."""

    return path(route, protect_dashboard_route(name, view), name=name)
