"""User workflow navigation independent of the delivery and QC state vocabulary.

The same metadata drives server filtering, counts, grouping and browser copy.
Status predicates still own lifecycle precedence and access-scoped review state.
"""

from enum import Enum

from .statuses import DeliveryStatus, delivery_status_sql


class DeliveryWorkflow(str, Enum):
    ACTION_REQUIRED = "action_required"
    RUNNING = "running"
    IN_REVIEW = "in_review"
    COMPLETED = "completed"
    ALL = "all"


ACTION_GROUPS = (
    {"value": "needs_correction", "label": "Review changes",
     "description": "Read the product manager’s feedback and upload a correction."},
    {"value": "failed", "label": "Resolve QC issues",
     "description": "Check the QC report and correct the delivery."},
    {"value": "not_validated", "label": "Run QC",
     "description": "Start quality checks before submitting the delivery."},
    {"value": "passed", "label": "Submit",
     "description": "Quality checks passed. Submit the delivery for review."},
)

WORKFLOW_CONFIG = {
    "action_required": {
        "label": "Action required",
        "description": "Work through corrections, QC issues and deliveries ready for the next step.",
        "statuses": [group["value"] for group in ACTION_GROUPS],
        "empty_message": "You’re all caught up. No deliveries need action.",
    },
    "running": {
        "label": "Running now",
        "description": "Quality checks are running or queued. Deliveries move automatically when checks finish.",
        "statuses": ["running"],
        "empty_message": "No quality checks are running or queued.",
    },
    "in_review": {
        "label": "In review",
        "description": "Submitted deliveries waiting for the product manager’s decision.",
        "statuses": ["submitted"],
        "empty_message": "No deliveries are waiting for review.",
    },
    "completed": {
        "label": "Completed",
        "description": "Accepted deliveries kept here for reference and reporting.",
        "statuses": ["accepted"],
        "empty_message": "No deliveries have been accepted yet.",
    },
    "all": {
        "label": "All deliveries",
        "description": "Search and inspect deliveries across every workflow stage.",
        "statuses": [status.value for status in DeliveryStatus
                     if status not in (DeliveryStatus.ALL, DeliveryStatus.ATTENTION)],
        "empty_message": "No deliveries yet.",
    },
}


class InvalidDeliveryWorkflow(ValueError):
    """An undeclared workflow must never silently broaden a list request."""


def parse_delivery_workflow(value):
    if value in (None, ""):
        return DeliveryWorkflow.ALL
    try:
        return DeliveryWorkflow(value)
    except (TypeError, ValueError) as exc:
        raise InvalidDeliveryWorkflow("Unknown delivery workflow view.") from exc


def classify_delivery_workflow(status):
    """Map one already classified leaf state to its primary workflow."""

    for workflow, config in WORKFLOW_CONFIG.items():
        if workflow != "all" and status in config["statuses"]:
            return workflow
    raise ValueError("A delivery row must have a declared leaf status.")


def delivery_workflow_sql(workflow):
    workflow = parse_delivery_workflow(workflow)
    if workflow is DeliveryWorkflow.ALL:
        return "", []
    clauses, parameters = [], []
    for status in WORKFLOW_CONFIG[workflow.value]["statuses"]:
        clause, values = delivery_status_sql(status)
        clauses.append("(" + clause.removeprefix(" AND ") + ")")
        parameters.extend(values)
    return " AND (" + " OR ".join(clauses) + ")", parameters


def delivery_priority_sql():
    """Sort actionable work first using the same rules as the status filters.

    Priority is an ascending workflow order, independent of a column's sort
    direction. The caller adds a stable newest-first delivery tie-breaker.
    """

    states = [group["value"] for group in ACTION_GROUPS] + [DeliveryStatus.RUNNING]
    clauses = []
    parameters = []
    for priority, status in enumerate(states):
        clause, clause_parameters = delivery_status_sql(status)
        clauses.append(f"WHEN {clause.removeprefix(' AND ')} THEN {priority}")
        parameters.extend(clause_parameters)
    return "CASE " + " ".join(clauses) + f" ELSE {len(states)} END", parameters


def delivery_workflow_counts(status_counts):
    counts = status_counts.as_dict()
    return {
        workflow: sum(counts[status] for status in config["statuses"])
        for workflow, config in WORKFLOW_CONFIG.items()
    }


def delivery_workflow_tabs(status_counts):
    counts = delivery_workflow_counts(status_counts)
    return tuple(
        {
            "value": workflow,
            "label": config["label"],
            "count": counts[workflow],
            "active": workflow == "action_required",
            "indicator": workflow == "running",
            "align_end": workflow == "all",
        }
        for workflow, config in WORKFLOW_CONFIG.items()
    )
