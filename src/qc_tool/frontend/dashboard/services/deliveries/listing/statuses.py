"""Stable, mutually exclusive states used by the delivery-list UI."""

from dataclasses import dataclass
from enum import Enum

from qc_tool.common import JOB_OK
from qc_tool.common import JOB_RUNNING
from qc_tool.common import JOB_WAITING


class DeliveryStatus(str, Enum):
    """The complete public filter vocabulary for Delivery rows."""

    ALL = "all"
    NOT_VALIDATED = "not_validated"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SUBMITTED = "submitted"


STATUS_LABELS = (
    (DeliveryStatus.ALL, "All"),
    (DeliveryStatus.NOT_VALIDATED, "Not validated"),
    (DeliveryStatus.RUNNING, "Running"),
    (DeliveryStatus.PASSED, "Passed"),
    (DeliveryStatus.FAILED, "Failed"),
    (DeliveryStatus.SUBMITTED, "Submitted"),
)


class InvalidDeliveryStatus(ValueError):
    """Raised when a request supplies an undeclared status filter."""


def parse_delivery_status(value):
    """Return a declared status and reject unknown values fail-closed."""

    if value in (None, ""):
        return DeliveryStatus.ALL
    try:
        return DeliveryStatus(value)
    except (TypeError, ValueError) as exc:
        raise InvalidDeliveryStatus("Unknown delivery status filter.") from exc


def classify_delivery_status(job_status, submitted_at=None):
    """Return exactly one user-facing state for a Delivery and latest Job."""

    if submitted_at is not None:
        return DeliveryStatus.SUBMITTED
    if job_status is None:
        return DeliveryStatus.NOT_VALIDATED
    if job_status in (JOB_WAITING, JOB_RUNNING):
        return DeliveryStatus.RUNNING
    if job_status == JOB_OK:
        return DeliveryStatus.PASSED

    # Success is allow-listed. Every other persisted state requires review,
    # including future or legacy worker values unknown to this frontend.
    return DeliveryStatus.FAILED


def delivery_status_sql(status):
    """Return a static SQL clause plus parameters for one status bucket."""

    status = parse_delivery_status(status)
    if status is DeliveryStatus.ALL:
        return "", []
    if status is DeliveryStatus.SUBMITTED:
        return " AND d.date_submitted IS NOT NULL", []

    unsubmitted = " AND d.date_submitted IS NULL"
    if status is DeliveryStatus.NOT_VALIDATED:
        return unsubmitted + " AND j.job_status IS NULL", []
    if status is DeliveryStatus.RUNNING:
        return unsubmitted + " AND j.job_status IN (%s, %s)", [
            JOB_WAITING,
            JOB_RUNNING,
        ]
    if status is DeliveryStatus.PASSED:
        return unsubmitted + " AND j.job_status = %s", [JOB_OK]

    non_failure_statuses = (JOB_WAITING, JOB_RUNNING, JOB_OK)
    placeholders = ", ".join(["%s"] * len(non_failure_statuses))
    return (
        unsubmitted
        + " AND j.job_status IS NOT NULL"
        + " AND j.job_status NOT IN ({})".format(placeholders),
        list(non_failure_statuses),
    )


@dataclass(frozen=True)
class DeliveryStatusCounts:
    """Access- and filter-scoped counts for the status navigation."""

    all: int
    not_validated: int
    running: int
    passed: int
    failed: int
    submitted: int

    def as_dict(self):
        return {
            "all": self.all,
            "not_validated": self.not_validated,
            "running": self.running,
            "passed": self.passed,
            "failed": self.failed,
            "submitted": self.submitted,
        }

    def as_tabs(self):
        values = self.as_dict()
        return tuple(
            {
                "value": status.value,
                "label": label,
                "count": values[status.value],
            }
            for status, label in STATUS_LABELS
        )
