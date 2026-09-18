"""Product workflow navigation derived from existing catalog state.

The caller supplies only the release states the account may classify. Workflow
counts and links therefore use the same scoped rows as the product table.
"""

from enum import Enum


class ProductWorkflow(str, Enum):
    ACTIVE = "active"
    DRAFT = "draft"
    STOPPED = "stopped"
    COMPLETED = "completed"


WORKFLOW_CONFIG = {
    "active": {
        "label": "Active",
        "description": "Products with approved delivery plans. Track deliveries and confirm readiness when every required product unit is accepted.",
        "empty_message": "Products appear here once their delivery plans are approved.",
    },
    "draft": {
        "label": "Draft",
        "description": "Review required units and assign a product manager to activate each product.",
        "empty_message": "New specifications appear here until their delivery plans are approved.",
    },
    "stopped": {
        "label": "Stopped",
        "description": "Products that have been stopped or whose delivery plans are retired. Their specifications and history remain available.",
        "empty_message": "Stopped products remain available here with their specification and delivery history.",
    },
    "completed": {
        "label": "Completed",
        "description": "Products with every required product unit accepted and final readiness confirmed by a product manager.",
        "empty_message": "Products appear here after all required units are accepted and a manager confirms final readiness.",
    },
}


class InvalidProductWorkflow(ValueError):
    """Unknown workflow values must never broaden the product list."""


def parse_product_workflow(value):
    if value in (None, ""):
        return ProductWorkflow.ACTIVE
    try:
        return ProductWorkflow(value)
    except (TypeError, ValueError) as exc:
        raise InvalidProductWorkflow("Unknown product workflow view.") from exc


def classify_product_workflow(*, is_active, coverage_states, is_ready=False):
    """Classify approved scope separately from explicit final confirmation.

    A mixed or undefined plan remains a draft. Acceptance of every unit alone
    never completes a product; ``is_ready`` must be a validated confirmation
    from the catalog readiness service, not merely a stored timestamp.
    """

    states = frozenset(coverage_states)
    if not is_active or states == {"retired"}:
        return ProductWorkflow.STOPPED
    if states != {"authoritative"}:
        return ProductWorkflow.DRAFT
    if is_ready:
        return ProductWorkflow.COMPLETED
    return ProductWorkflow.ACTIVE


def can_show_product_workflow(workflow, *, account_access, has_completed_products=False):
    """Expose management stages only to catalog administrators."""

    return (
        account_access.can_manage_product_catalog
        or workflow == ProductWorkflow.ACTIVE
        or (workflow == ProductWorkflow.COMPLETED and has_completed_products)
    )


def product_workflow_tabs(products, *, selected, base_url, account_access):
    """Build permitted tabs using only already authorized product counts."""

    counts = {workflow: 0 for workflow in WORKFLOW_CONFIG}
    for product in products:
        counts[product["workflow"]] += 1
    return tuple(
        {
            "value": workflow,
            "label": config["label"],
            "count": counts[workflow],
            "url": f"{base_url}?product_view={workflow}",
            "active": workflow == selected,
        }
        for workflow, config in WORKFLOW_CONFIG.items()
        if can_show_product_workflow(
            workflow, account_access=account_access,
            has_completed_products=counts[ProductWorkflow.COMPLETED] > 0,
        )
    )
