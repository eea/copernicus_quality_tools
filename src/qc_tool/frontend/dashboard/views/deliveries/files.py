"""Authorized delivery file downloads."""

from django.http import FileResponse
from django.http import Http404
from django.shortcuts import get_object_or_404
import qc_tool.frontend.dashboard.models as models
from qc_tool.frontend.accounts.authorization import access_for_request
from qc_tool.frontend.dashboard.access import require_delivery_view
from qc_tool.frontend.dashboard.services.artifacts import ArtifactUnavailable
from qc_tool.frontend.dashboard.services.artifacts.inputs import open_delivery_input


def download_delivery_file(request, delivery_id):
    delivery = get_object_or_404(models.Delivery, pk=int(delivery_id))
    require_delivery_view(access_for_request(request), delivery)

    # File existence check.
    if delivery.is_deleted:
        raise Http404("Uploaded file for delivery id={:d} has been deleted by the user.".format(int(delivery_id)))

    # Downloading the delivery Zip file.
    try:
        delivery_file = open_delivery_input(delivery)
    except ArtifactUnavailable:
        raise Http404()
    return FileResponse(
        delivery_file,
        content_type="application/zip",
        as_attachment=True,
        filename=delivery.filename,
    )
