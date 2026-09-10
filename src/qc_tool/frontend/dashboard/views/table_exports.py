"""Convert browser table snapshots using the application export service."""

from django.http import JsonResponse

from qc_tool.frontend.accounts.http import prevent_private_response_caching
from qc_tool.frontend.dashboard.services.exports import InvalidTableExport, table_export_response
from qc_tool.frontend.dashboard.services.exports.browser import MAX_EXPORT_BYTES, parse_browser_export


def table_export(request):
    if request.content_type != "application/json":
        return JsonResponse({"error": "Use JSON to request a table export."}, status=415)
    # Bounded stream reading keeps this conversion endpoint independent of the
    # separate multipart upload limits. No request payload is saved to the DB.
    body = request.read(MAX_EXPORT_BYTES + 1)
    if len(body) > MAX_EXPORT_BYTES:
        return JsonResponse({"error": "This export is too large. Narrow the filters and try again."}, status=413)
    try:
        snapshot = parse_browser_export(body)
    except InvalidTableExport as error:
        return JsonResponse({"error": str(error)}, status=400)
    return prevent_private_response_caching(table_export_response(
        iter(snapshot.rows), snapshot.columns, format=snapshot.format,
        filename=snapshot.filename,
    ))
