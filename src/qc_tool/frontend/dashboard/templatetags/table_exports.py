"""Expose the shared export contract for each page's authorized endpoint."""

from django import template
from django.templatetags.static import static
from django.urls import reverse

from qc_tool.frontend.dashboard.services.exports import EXPORT_FORMAT_OPTIONS


register = template.Library()


@register.simple_tag
def table_export_config(route_name="table_export"):
    return {
        "url": reverse(route_name),
        "formats": EXPORT_FORMAT_OPTIONS,
        "iconSprite": static("dashboard/icons/ui.svg"),
    }
