"""One navigation contract for storage libraries and the file browser."""

from urllib.parse import urlencode

from django.urls import reverse


TASKS = (
    ("deliveries", "Submitted deliveries"),
    ("specifications", "Product specifications"),
    ("boundaries", "Boundaries"),
    ("files", "Browse files"),
    ("connection", "Connect with SFTP"),
)
LIBRARIES = frozenset({"deliveries", "specifications", "boundaries"})


def url(name="admin_storage", **values):
    return reverse(name) + ("?" + urlencode(values, doseq=True) if values else "")


def browse_url(**values):
    values.setdefault("tab", "files")
    return url(**values)


def tasks(active):
    return [{"key": key, "label": label, "url": url(tab=key), "active": key == active}
            for key, label in TASKS]


def locations(areas):
    """Keep physical mount locations distinct from the logical libraries."""
    return [{**area, "url": browse_url(area=area["key"])} for area in areas if area["key"] != "jobs"]
