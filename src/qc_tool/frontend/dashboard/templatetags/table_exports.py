"""Expose the application export contract once per workspace page."""

from django import template
from django.templatetags.static import static
from django.urls import reverse

from qc_tool.frontend.dashboard.services.exports import EXPORT_FORMAT_OPTIONS


register = template.Library()


@register.simple_tag
def table_export_config():
    return {
        "url": reverse("table_export"),
        "formats": EXPORT_FORMAT_OPTIONS,
        "iconSprite": static("dashboard/icons/ui.svg"),
    }
