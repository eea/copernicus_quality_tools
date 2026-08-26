"""Convert delivery and job records to display-safe activity facts."""

from qc_tool.frontend.dashboard.services.deliveries import classify_job_status

from ...contracts import ActivityItem


def build_job_activity(job, account_access):
    """Describe one dated QC event without embedding markup."""

    category = classify_job_status(job.job_status)
    if category == "passed":
        title = "{} passed QC".format(job.delivery.filename)
        tone = "success"
    elif category == "in_progress":
        title = "QC in progress for {}".format(job.delivery.filename)
        tone = "progress"
    elif category == "failed":
        title = "{} needs QC attention".format(job.delivery.filename)
        tone = "danger"
    elif category == "not_checked":
        title = "{} is ready for QC".format(job.delivery.filename)
        tone = "neutral"
    else:
        title = "QC status updated for {}".format(job.delivery.filename)
        tone = "neutral"
    return ActivityItem(
        kind="qc",
        tone=tone,
        title=title,
        detail=build_activity_detail(
            job.product_description or job.product_ident or "QC job",
            job.delivery.user.username,
            account_access,
        ),
        occurred_at=job.activity_at,
    )


def build_activity_detail(description, username, account_access):
    """Include actor identity only when the caller may see other users."""

    if account_access.can_view_other_users_deliveries:
        return "{} · {}".format(description, username)
    return description
