"""One administrator journey determines both explanatory copy and its next action."""

from dataclasses import dataclass, replace

from .presentation import initializes_history


@dataclass(frozen=True)
class NextStep:
    title: str
    description: str
    stage: int
    target: str
    label: str


def _preparation(overview, initializes, eligible_backup):
    state = overview.get("database", {}).get("state")
    if state == "ready":
        return NextStep("No database upgrade is needed",
            "The active schema and migration history match this installation. Applied migrations and previous upgrade operations remain available below.",
            0, "applied", "View applied migrations")
    if state not in {"legacy", "pending"}:
        return NextStep("Check database availability",
            "Refresh the overview after resolving the reported connection or inspection problem. No upgrade action has been started.",
            0, "help", "Review intervention guidance")
    if overview.get("maintenance", {}).get("phase") != "ready":
        detail = " before initializing Django migration history on a verified copy" if initializes else ""
        return NextStep("Turn on maintenance",
            "Open Maintenance and wait for every worker to acknowledge the pause. Then create or review a complete backup" + detail + ".",
            1, "maintenance", "Open maintenance")
    if not overview.get("can_prepare"):
        task = "initializing Django migration history on a verified copy" if initializes else "preparing an upgrade"
        return NextStep("Resolve the initialization prerequisites" if initializes else "Resolve the upgrade prerequisites",
            f"Review the requirements above before {task}. The current source and recovery evidence remain retained.",
            1, "help", "Review intervention guidance")
    if not eligible_backup:
        task = "initializing Django migration history on a verified copy" if initializes else "preparing an upgraded copy"
        return NextStep("Create a complete backup",
            f"Include the database and all retained file sections. Review missing or external content before {task}.",
            1, "export", "Create complete backup")
    if initializes:
        return NextStep("Initialize Django migration history",
            "This v3.0.0 database has no Django migration history. Review a complete backup, initialize history on a separate verified copy, then explicitly switch to it. The installed QC Tool version remains v3.0.0.",
            1, "backups", "Choose a backup to review")
    return NextStep("Review a backup",
        "Choose a complete backup below. Review checks the current source and retained files without starting an upgrade.",
        1, "backups", "Choose a backup to review")


def _review(review, initializes):
    if not review.get("can_apply"):
        return NextStep("Resolve the review blockers",
            "No upgrade has been started. Resolve the reported blockers and review the backup again before preparing a copy.",
            1, "review", "Continue backup review")
    detail = ("Django migration history will be initialized only on a separate copy" if initializes else "no migration has started yet")
    return NextStep("Review history initialization, then prepare a copy" if initializes else "Review the plan, then prepare a copy",
        f"The source and storage inventory have been checked for this review. Read the warnings and confirm preparation below; {detail}.",
        2, "review", "Continue backup review")


def next_step(page, *, operation_active, current_operation, backups):
    overview, operation = page.overview, page.operation
    state = page.database.get("state")
    phase = overview.get("maintenance", {}).get("phase")
    initializes = initializes_history(overview, operation)
    if current_operation.get("transfer_url") and not operation:
        return NextStep("Complete the current database operation",
            "Another operation owns maintenance. Open its progress and recovery page before preparing another upgrade.",
            2, current_operation["transfer_url"], "Open current operation")
    if page.review:
        return _review(page.review, initializes)
    if state == "unavailable":
        return NextStep("Restore database access before continuing",
            "Turn on maintenance if it is off. Upgrade journals and recovery copies remain retained, but the source cannot be verified. Restore access and refresh the overview before choosing a recovery action.",
            2 if operation else 1, "help", "Review intervention guidance")
    if state in {"incompatible", "empty"}:
        return NextStep("Investigate the database before upgrading",
            "Turn on maintenance if it is off. Preserve a complete backup and investigate the reported schema or migration-history differences. This page will not repair or guess migration history.",
            1, "help", "Review intervention guidance")
    preparation = _preparation(overview, initializes, any(item.get("eligible") for item in backups))
    if operation_active:
        if state != "ready":
            return replace(preparation, title="Prepare the next release upgrade", stage=1,
                description="This operation selected the active database for an earlier migration plan. The current installation still has pending migrations; prepare a new reviewed copy before reopening.")
        if phase == "off":
            return NextStep("History initialization complete; QC Tool is open" if initializes else "Upgrade complete; QC Tool is open",
                "The active database matches the installed migration graph. The previous database and recovery evidence remain retained.",
                3, "history", "View past upgrades")
        return NextStep("Finish the initialization checks" if initializes else "Finish the post-upgrade checks",
            "Check administrator access, records and retained files, then reopen QC Tool through Maintenance. The previous database remains retained for reviewed recovery.",
            3, "maintenance", "Finish checks & reopen")
    if not operation:
        return preparation
    status = operation.get("status")
    if status == "completed":
        return NextStep("Review the database switch" if phase == "ready" else "Turn on maintenance before switching",
            "The copy has completed migration and verification. Review the source, destination, retained files and administrator access before explicitly selecting it.",
            3, "operation" if phase == "ready" else "maintenance",
            "Review database switch" if phase == "ready" else "Open maintenance before switching")
    if status in {"queued", "running"}:
        return NextStep("Wait for copy verification",
            "Preparation continues in the background. The active database stays in use until you approve a separate switch.",
            2, "operation", "View progress & recovery")
    if status == "recovery_required" or operation.get("recoverable"):
        return NextStep("Choose a recovery action",
            "The source and recovery evidence are retained. Use the available actions below; an uncertain migration is never repeated automatically.",
            2, "operation", "View progress & recovery")
    if status == "failed":
        return NextStep("The upgrade is stopped",
            "The failed copy and its evidence are retained. Review a fresh backup to prepare another copy when the source is ready.",
            1, "operation", "View progress & recovery")
    return replace(preparation, target="operation", label="View progress & recovery")
