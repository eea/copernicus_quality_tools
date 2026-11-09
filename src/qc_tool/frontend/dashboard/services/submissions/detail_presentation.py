"""Query-free status, decision guidance and retained evidence for a receipt."""

from pathlib import PurePosixPath

from .approval_presentation import submission_approval
from .status import submission_status


def submission_detail_presentation(
    submission, *, can_review, storage_available, files, conflict=None, events=(),
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
        "status": submission_status(
            submission, can_review=can_review, storage_available=storage_available,
            events=events, conflict=conflict,
        ),
        "approval": submission_approval(submission, events=events, conflict=conflict),
        "decision": {
            "can_decide": can_decide,
            "can_approve": bool(can_accept and not has_open_conflict),
            "can_reject": can_decide,
            "can_replace": bool(can_accept and has_open_conflict),
            "approval_block_reason": approval_block_reason,
        },
        "evidence": _evidence(submission.delivery.filename, files),
    }


def _evidence(filename, files):
    retained_files = list(files)
    names = {item["name"] for item in retained_files}
    report_name = "{}_report.pdf".format(PurePosixPath(filename).stem)
    report_name = next((name for name in (
        "reports/" + report_name, report_name, "reports/report.pdf", "report.pdf",
    ) if name in names), "report.pdf")
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
