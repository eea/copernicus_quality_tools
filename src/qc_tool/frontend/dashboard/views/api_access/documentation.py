"""Public API documentation endpoints."""

from django.http import JsonResponse
from django.shortcuts import render
from qc_tool.common import CONFIG
from qc_tool.frontend.dashboard.services.api import api_documentation_context
from qc_tool.frontend.dashboard.services.api import openapi_document


def api_homepage(request):
    return render(
        request,
        "dashboard/api_access/index.html",
        api_documentation_context(CONFIG["api_url"]),
    )


def api_openapi_json(request):
    return JsonResponse(openapi_document(CONFIG["api_url"]))
