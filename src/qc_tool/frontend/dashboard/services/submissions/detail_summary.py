"""Loaded submission identity and decisions presented through the shared card."""

from django.urls import reverse

from qc_tool.frontend.dashboard.services.catalog.version_identity import release_version_identity


def submission_summary(submission, status):
    release = submission.product_release
    version = release_version_identity(release, submission.job.qc_definition)
    return {
        "kind": "Submitted delivery", "icon": "file",
        "reference": "#{}".format(submission.delivery_id),
        "title": submission.delivery.filename,
        "description_label": "Product", "description": release.product.name,
        "description_url": reverse("product_detail", args=(release.product.ident,)),
        "status_label": "Review status", "status": status,
        "status_description": status["message"],
        "facts": [
            {"label": "Product unit", "value": submission.product_unit_code},
            {"label": "Specification set", "value": version["label"]},
            {"label": "Version selection", "value": version["selection_label"]},
            {"label": "Exact specification", "value": version["definition_ident"] or "Not recorded"},
            {"label": "Specification SHA-256", "value": version["definition_digest"] or "Not recorded"},
            {"label": "Submitted by", "value": submission.submitted_by_username},
            {"label": "Submitted on", "datetime": submission.requested_at},
            {"label": "QC result", "value": "Passed" if submission.job.job_status == "ok" else "Not passed"},
        ],
    }
