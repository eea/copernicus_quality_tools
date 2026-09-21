"""Query-free status, decision guidance and retained evidence for a receipt."""

from pathlib import PurePosixPath


def submission_detail_presentation(
    submission, *, can_review, storage_available, files, conflict=None,
):
    """Present loaded receipt data without changing review or download policy.

    The caller supplies permission-scoped submission relations and file URLs
    from the retained inventory. Storage availability affects guidance only:
    the review service remains responsible for validating every decision.
    """

    can_decide = bool(
        can_review
        and submission.publication_state == "published"
        and submission.review_state in {"pending", "conflict"}
    )
    approval_block_reason = ""
    if can_decide:
        release = submission.product_release
        if not release.product.is_active:
            approval_block_reason = (
                "This product is stopped. Restore it before approving submissions."
            )
        elif release.coverage_state != "authoritative":
            approval_block_reason = (
                "The delivery plan must be approved before this submission can be approved."
            )
    can_accept = can_decide and not approval_block_reason
    has_open_conflict = conflict is not None and conflict.state == "open"

    return {
        "status": _status(
            submission, can_review=can_review, storage_available=storage_available,
        ),
        "decision": {
            "can_decide": can_decide,
            "can_approve": bool(can_accept and not has_open_conflict),
            "can_reject": can_decide,
            "can_replace": bool(can_accept and has_open_conflict),
            "approval_block_reason": approval_block_reason,
        },
        "evidence": _evidence(submission.delivery.filename, files),
    }


def _status(submission, *, can_review, storage_available):
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

    state = submission.review_state
    if state == "accepted":
        message = (
            "This delivery is approved for its product unit in the current delivery plan."
            if submission.product_release.is_current
            else "This delivery was approved for an earlier delivery plan. "
            "Its evidence and review decision remain available."
        )
        label, tone = "Approved", "success"
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


def _evidence(filename, files):
    retained_files = list(files)
    names = {item["name"] for item in retained_files}
    report_name = "{}_report.pdf".format(PurePosixPath(filename).stem)
    if report_name not in names:
        report_name = "report.pdf"
    highlights = (
        ("input.d/{}".format(filename), "submitted ZIP", "package"),
        (report_name, "QC report", "file"),
    )
    primary_files = []
    primary_indexes = set()
    for name, label, icon in highlights:
        for index, item in enumerate(retained_files):
            if item["name"] == name:
                primary_files.append({**item, "label": label, "icon": icon})
                primary_indexes.add(index)
                break
    return {
        "primary_files": primary_files,
        "supporting_files": [
            item for index, item in enumerate(retained_files) if index not in primary_indexes
        ],
    }
