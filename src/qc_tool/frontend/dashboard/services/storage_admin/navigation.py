"""One navigation contract for storage libraries and the file browser."""

from urllib.parse import urlencode

from django.urls import reverse


TASKS = (
    ("files", "Browse files"),
    ("history", "File history"),
    ("connection", "Connection"),
)
HISTORY_TASKS = (
    ("deliveries", "Submitted deliveries"),
    ("specifications", "Product specifications"),
    ("boundaries", "Boundary versions"),
)
LIBRARIES = frozenset({"deliveries", "specifications", "boundaries"})


def library_key(tab, collection=""):
    """Recognize saved collection links without changing physical folder context."""
    if tab in LIBRARIES:
        return tab
    if tab == "history":
        return collection if collection in LIBRARIES else "deliveries"
    return ""


def url(name="admin_storage", **values):
    if name == "admin_storage" and values.get("tab") in LIBRARIES:
        values = {**values, "collection": values["tab"], "tab": "history"}
    return reverse(name) + ("?" + urlencode(values, doseq=True) if values else "")


def browse_url(**values):
    values.setdefault("tab", "files")
    return url(**values)


def tasks(active):
    section = "history" if active in LIBRARIES else active
    return [{"key": key, "label": label, "url": url(tab=key), "active": key == section}
            for key, label in TASKS]


def history_tasks(active):
    return [{"key": key, "label": label, "url": url(tab=key), "active": key == active}
            for key, label in HISTORY_TASKS]


def locations(areas):
    """Keep physical mount locations distinct from the logical libraries."""
    return [{**area, "url": browse_url(area=area["key"])} for area in areas if area["key"] != "jobs"]
