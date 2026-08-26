"""Merge recent database records into one bounded activity stream."""

from ...contracts import ActivityItem
from .presentation import build_activity_detail
from .presentation import build_job_activity
from .sources import recent_activity_sources


def build_recent_activity(deliveries, *, account_access, limit):
    """Return recent QC, upload, and submission events in time order."""

    jobs, uploads, submissions = recent_activity_sources(
        deliveries,
        limit=limit,
    )

    activity = []
    for job in jobs:
        activity.append(build_job_activity(job, account_access))
    for delivery in uploads:
        activity.append(
            ActivityItem(
                kind="upload",
                tone="info",
                title="{} uploaded".format(delivery.filename),
                detail=build_activity_detail(
                    delivery.product_description or "Delivery uploaded",
                    delivery.user.username,
                    account_access,
                ),
                occurred_at=delivery.date_uploaded,
            )
        )
    for delivery in submissions:
        activity.append(
            ActivityItem(
                kind="submission",
                tone="submitted",
                title="{} submitted to EEA".format(delivery.filename),
                detail=build_activity_detail(
                    delivery.product_description or "Submission completed",
                    delivery.user.username,
                    account_access,
                ),
                occurred_at=delivery.date_submitted,
            )
        )

    activity.sort(key=lambda item: item.occurred_at, reverse=True)
    return tuple(activity[:limit])
