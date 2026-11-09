"""Describe approved selections and prior decisions without changing them."""


def submission_approval(submission, *, events=(), conflict=None):
    """Read loaded review evidence; QC success never establishes approval."""

    approved = submission.publication_state == "published" and submission.review_state == "accepted"
    previously_approved = any(event.decision == "approved" for event in events)
    selected_id = getattr(conflict, "selected_submission_id", None)
    replaced = bool(
        submission.publication_state == "published"
        and submission.review_state == "rejected" and previously_approved
        and selected_id is not None and selected_id != submission.pk
    )
    return {
        "is_approved_selection": approved,
        "historical_revision": not submission.product_release.is_current,
        "previously_approved": previously_approved,
        "replaced": replaced,
        "selected_submission_id": selected_id if replaced else None,
    }
