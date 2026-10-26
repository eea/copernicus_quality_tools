"""Read-only workspace announcements and their shared presentation state."""

from django.shortcuts import render
from qc_tool.frontend.dashboard.services.configuration.presentation import announcement_context


def announcement(request):
    """Render the current announcement for an authenticated QC Tool user."""

    return render(
        request, "dashboard/configuration/announcement.html", announcement_context(),
    )
