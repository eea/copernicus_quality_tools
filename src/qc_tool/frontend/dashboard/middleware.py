from django.shortcuts import render
from django.conf import settings

class MaintenanceModeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(settings, "MAINTENANCE_MODE", False):

            # allow admin access
            if request.path.startswith("/admin/"):
                return self.get_response(request)

            return render(
                request,
                "dashboard/maintenance.html",
                status=503
            )

        return self.get_response(request)