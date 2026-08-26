"""Immutable values rendered by the workspace dashboard.

These contracts contain display-safe facts, not HTML or authorization rules.
Every delivery-derived value is calculated from the caller's effective
``AccountAccess`` scope.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class DeliveryOverview:
    """Delivery and latest-QC counts for one effective access scope."""

    total_deliveries: int
    uploaded_last_7_days: int
    qc_passed: int
    qc_in_progress: int
    qc_failed: int
    not_checked: int
    unknown_status: int
    submitted_deliveries: int
    ready_to_submit: int
    submission_in_progress: int
    coverage_attention: int

    @property
    def needs_attention(self):
        """Deliveries whose latest QC state needs a user decision."""

        return self.qc_failed + self.not_checked + self.unknown_status

    @property
    def passed_percentage(self):
        return _whole_percentage(self.qc_passed, self.total_deliveries)

    @property
    def submitted_percentage(self):
        return _whole_percentage(
            self.submitted_deliveries,
            self.total_deliveries,
        )


@dataclass(frozen=True)
class CoverageSegment:
    """One exhaustive segment of the delivery submission lifecycle."""

    key: str
    label: str
    count: int
    percentage: float
    offset: float

    @property
    def remainder(self):
        """Remaining circumference used by the accessible SVG ring."""

        return round(100.0 - self.percentage, 4)

    @property
    def display_percentage(self):
        return int(round(self.percentage))


@dataclass(frozen=True)
class ProductAttention:
    """Latest-QC aggregate for one product represented by visible deliveries."""

    identifier: str
    description: str
    total_deliveries: int
    qc_passed: int
    qc_in_progress: int
    needs_attention: int

    @property
    def passed_percentage(self):
        return _whole_percentage(self.qc_passed, self.total_deliveries)


@dataclass(frozen=True)
class ActivityItem:
    """A bounded recent event derived from existing delivery and job records."""

    kind: str
    tone: str
    title: str
    detail: str
    occurred_at: datetime


@dataclass(frozen=True)
class WorkspaceDashboard:
    """Complete access-scoped dashboard snapshot."""

    summary: DeliveryOverview
    coverage: tuple
    product_attention: tuple
    recent_activity: tuple


def _whole_percentage(part, total):
    if total <= 0:
        return 0
    return int(round((part / total) * 100))
