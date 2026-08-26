"""Build the exhaustive delivery-lifecycle coverage segments."""

from ..contracts import CoverageSegment


def build_coverage_segments(summary):
    """Map the delivery summary to ordered, disjoint coverage segments."""

    values = (
        ("submitted", "Submitted", summary.submitted_deliveries),
        ("ready", "Ready to submit", summary.ready_to_submit),
        (
            "in_progress",
            "QC in progress",
            summary.submission_in_progress,
        ),
        ("blocked", "Needs attention", summary.coverage_attention),
    )
    segments = []
    offset = 0.0
    for key, label, count in values:
        percentage = _percentage(count, summary.total_deliveries)
        segments.append(
            CoverageSegment(
                key=key,
                label=label,
                count=count,
                percentage=percentage,
                offset=round(offset, 4),
            )
        )
        offset += percentage
    return tuple(segments)


def _percentage(part, total):
    if total <= 0:
        return 0.0
    return round((part / total) * 100.0, 4)
