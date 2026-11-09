"""Query-free storage and review status for retained submissions."""

from .approval_presentation import submission_approval


def submission_status(submission, *, can_review=False, storage_available=False, events=(), conflict=None):
    """Describe a loaded receipt without queries, actions or URL assumptions."""
    publication = submission.publication_state
    if publication != "published":
        label, tone, message = {
            "pending": (
                "Preparing submission", "primary",
                "The submitted delivery and QC evidence are waiting to be stored. "
                "Review can begin once this completes.",
            ),
            "publishing": (
                "Storing submission", "primary",
                "The submitted delivery and QC evidence are being stored. "
                "Review can begin once this completes.",
            ),
            "failed": (
                "Submission failed", "danger",
                "The delivery could not be stored for review. "
                "A review decision cannot be recorded yet.",
            ),
        }.get(publication, (
            "Submission unavailable", "warning",
            "The submission is not available for review.",
        ))
        return {"value": publication, "label": label, "tone": tone, "message": message}

    approval = submission_approval(submission, events=events, conflict=conflict)
    state = submission.review_state
    if state == "accepted":
        message = (
            "This delivery is the approved selection for its product unit and specification-set revision. "
            "This is the current revision for its series."
            if submission.product_release.is_current
            else "This delivery is the approved selection for its historical specification-set revision "
            "and product unit. No approval is implied for another revision."
        )
        label, tone = "Approved", "success"
    elif state == "rejected" and approval["previously_approved"]:
        label, tone = "Replaced" if approval["replaced"] else "Previously approved", "warning"
        message = "This delivery was approved previously and is no longer the approved selection for this unit and revision. Its evidence and decisions remain available."
    elif state == "rejected":
        label, tone = "Rejected", "danger"
        message = "This delivery was not accepted. Review the recorded feedback below."
    elif state == "conflict":
        label, tone = "Competing submissions", "warning"
        message = (
            "Several deliveries were submitted for this product unit. "
            "A product manager must choose a delivery or request corrections."
        )
    elif state == "pending":
        label, tone = "Awaiting review", "warning"
        message = (
            "Review the submitted delivery and QC evidence, then record your decision below."
            if can_review and storage_available
            else "A product manager must review this submission before it can be approved."
        )
    else:
        label, tone = "Review unavailable", "warning"
        message = "The review status is unavailable."
    return {"value": state, "label": label, "tone": tone, "message": message}


