"""Server-owned destinations for migration tasks and their return journey."""

from urllib.parse import urlencode

from django.urls import reverse


def migration_url(operation_id=""):
    url = reverse("admin_migrations")
    return url + "?" + urlencode({"operation": operation_id}) if operation_id else url


def maintenance_url(operation_id=""):
    return reverse("admin_maintenance") + "?" + urlencode({"next": migration_url(operation_id)})
