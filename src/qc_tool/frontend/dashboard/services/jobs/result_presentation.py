"""Read-only, human-readable presentation of a single historical QC run."""

from datetime import datetime
import re

from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from qc_tool.common import (
    JOB_ERROR, JOB_FAILED, JOB_LOST, JOB_OK, JOB_PARTIAL, JOB_RUNNING,
    JOB_TIMEOUT, JOB_WAITING,
)
from qc_tool.frontend.dashboard.access import can_manage_delivery
from qc_tool.frontend.dashboard.models import DeliverySubmission, Job
from qc_tool.frontend.dashboard.services.artifacts import ArtifactUnavailable, open_job_report
from qc_tool.frontend.dashboard.services.deliveries.product_links import add_delivery_product_links


_FILTERS = (
    ("all", "All checks"),
    ("attention", "Needs attention"),
    ("passed", "Passed"),
    ("not_run", "Not run"),
    ("in_progress", "In progress"),
)
_STEP_STATES = {
    "ok": ("Passed", "success", "passed"),
    "failed": ("Failed", "danger", "attention"),
    "aborted": ("Stopped early", "danger", "attention"),
    "error": ("Error", "danger", "attention"),
    "partial": ("Partially checked", "warning", "attention"),
    "cancelled": ("Cancelled", "warning", "attention"),
    "skipped": ("Skipped", "neutral", "not_run"),
    None: ("Not started", "neutral", "not_run"),
    "": ("Not started", "neutral", "not_run"),
    "running": ("Running", "warning", "in_progress"),
    "waiting": ("Waiting", "neutral", "in_progress"),
}
_JOB_STATES = {
    JOB_OK: ("Passed", "success"),
    JOB_FAILED: ("Failed", "danger"),
    JOB_PARTIAL: ("Partially checked", "warning"),
    JOB_ERROR: ("Job error", "danger"),
    JOB_WAITING: ("In queue", "warning"),
    JOB_RUNNING: ("In progress", "warning"),
    JOB_TIMEOUT: ("Timed out", "danger"),
    JOB_LOST: ("Worker unavailable", "danger"),
}


def build_result_presentation(job, report, account_access, selected_filter=""):
    """Enrich display copies without changing the downloadable report contract."""

    steps = [_present_step(step, index) for index, step in enumerate(report.get("steps", []), 1)]
    counters = {"total": len(steps), "passed": 0, "attention": 0, "not_run": 0, "in_progress": 0}
    for step in steps:
        counters[step["category"]] += 1
    if not selected_filter:
        selected_filter = "attention" if counters["attention"] else "all"
    elif selected_filter not in dict(_FILTERS):
        selected_filter = "all"
    elif selected_filter != "all" and not counters[selected_filter]:
        selected_filter = "all"
    filters = [
        {"key": key, "label": label, "count": counters["total" if key == "all" else key],
         "active": key == selected_filter, "url": f"?checks={key}#job-result-checks"}
        for key, label in _FILTERS
        if key == "all" or counters[key]
    ]
    visible_steps = [step for step in steps if selected_filter == "all" or step["category"] == selected_filter]
    aborted = next((step["title"] for step in steps if step.get("status") == "aborted"), "")
    status = report.get("status") or job.job_status
    return {
        "summary": _summary(job, report, account_access, status),
        "outcome": _outcome(status, aborted),
        "counters": counters,
        "filters": filters,
        "steps": visible_steps,
        "has_layers": any(step.get("layers") for step in visible_steps),
        "has_attachments": any(step.get("attachment_filenames") for step in visible_steps),
        "selected_filter": selected_filter,
        "checks_title": dict(_FILTERS)[selected_filter],
        "checks_description": (
            "Review these checks and their messages before running QC again."
            if selected_filter == "attention" else
            "Skipped and unstarted checks have no validation result."
            if selected_filter == "not_run" else
            "These checks completed successfully; supporting messages and files are shown below."
            if selected_filter == "passed" else
            "These checks are waiting or still running. Reload the page for updated results."
            if selected_filter == "in_progress" else
            "Checks are listed in execution order, with their results and supporting files."
        ),
        "aborted_check": aborted,
        "can_download_pdf": _pdf_available(job),
    }


def _present_step(step, index):
    presented = dict(step)
    identifier = str(step.get("check_ident") or "")
    display_ident = identifier.removeprefix("qc_tool.")
    title = re.sub(r"[_-]+", " ", display_ident.rsplit(".", 1)[-1]).strip()
    state = _STEP_STATES.get(step.get("status"), ("Unknown result", "warning", "attention"))
    presented.update(
        title=title[:1].upper() + title[1:] if title else f"Check {index}",
        display_ident=display_ident,
        number=step.get("step_nr") or index,
        status_label=state[0], status_tone=state[1], category=state[2],
    )
    return presented


def _summary(job, report, account_access, status):
    # Only the selected historical run can establish a catalog association.
    row = {"product_ident": job.product_ident, "last_job_uuid": job.pk}
    add_delivery_product_links([row], account_access)
    started = _datetime(report.get("job_start_date")) or _datetime(job.date_started)
    finished = _datetime(report.get("job_finish_date")) or _datetime(job.date_finished)
    facts = [{"label": "Started", "datetime": started, "value": "Not started"}]
    if finished:
        facts.append({"label": "Finished", "datetime": finished})
    if started and finished:
        duration = _duration(started, finished)
        if duration:
            facts.append({"label": "Duration", "value": duration})
    if job.product_unit_code:
        facts.append({"label": "Product unit", "value": job.product_unit_code})
    label, tone = _JOB_STATES.get(status, ("Unknown", "neutral"))
    return {
        "kind": "Delivery", "reference": f"#{job.delivery_id}", "icon": "file",
        "title": report.get("filename") or job.delivery.filename,
        "description": report.get("description") or job.product_description or job.product_ident,
        "description_label": "Checked against", "description_url": row["product_url"],
        "status_label": "This QC run",
        "status": {"value": status, "label": label, "tone": tone},
        "facts": facts, "action": _rerun_action(job.delivery, account_access),
    }


def _rerun_action(delivery, account_access):
    if (
        delivery.is_deleted or delivery.date_submitted is not None
        or not account_access.can_run_qc or not can_manage_delivery(account_access, delivery)
        or DeliverySubmission.objects.filter(delivery_id=delivery.pk).exists()
        or Job.objects.filter(delivery_id=delivery.pk, job_status__in=(JOB_RUNNING, JOB_WAITING)).exists()
    ):
        return None
    return {"label": "Run QC again", "url": f"{reverse('setup_job')}?deliveries={delivery.pk}", "icon": "play"}


def _outcome(status, aborted):
    if status == JOB_FAILED and aborted:
        return {"title": "QC job stopped early", "tone": "danger", "icon": "alert-triangle",
                "message": f"The {aborted} check stopped the run because later checks could be unreliable. Review its messages below; checks that did not run are not validated."}
    outcomes = {
        JOB_OK: ("QC passed", "All configured checks completed successfully. This is the result of this run; the delivery's review status is available in its job history.", "success", "check-circle"),
        JOB_FAILED: ("QC failed", "One or more checks need attention. Review their messages and supporting files before running QC again.", "danger", "alert-triangle"),
        JOB_PARTIAL: ("QC is incomplete", "Some checks were skipped, so this run does not provide a complete validation. Review the checks that did not run.", "warning", "alert-triangle"),
        JOB_ERROR: ("QC job error", "The run ended with a processing error. Review the error details and job log to understand what prevented validation.", "danger", "x-circle"),
        JOB_WAITING: ("QC is queued", "The job is waiting for a worker. No final result is available yet. Reload this page to check its progress.", "warning", "clock"),
        JOB_RUNNING: ("QC is running", "Results are provisional while the checks are running. Reload this page to check progress.", "warning", "clock"),
        JOB_TIMEOUT: ("QC timed out", "The worker exceeded the time limit. This run did not complete; review the job log before trying again.", "danger", "clock"),
        JOB_LOST: ("QC worker is unavailable", "The worker could no longer be reached. This run has no confirmed completion; review the job log or contact an administrator.", "danger", "alert-triangle"),
    }
    title, message, tone, icon = outcomes.get(status, ("QC result unavailable", "A final outcome is not available. Review the job log for more information.", "neutral", "help-circle"))
    return {"title": title, "message": message, "tone": tone, "icon": icon}


def _datetime(value):
    if isinstance(value, str):
        try:
            value = parse_datetime(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    aware = timezone.make_aware(value) if timezone.is_naive(value) else value
    # Templates do not convert UTC timestamps when the application uses
    # USE_TZ=False. Match the history page's explicitly labelled local dates.
    return timezone.localtime(aware)


def _duration(started, finished):
    seconds = int(_datetime(finished).timestamp() - _datetime(started).timestamp())
    if seconds < 0:
        return None
    if seconds == 0:
        return "Less than 1 second"
    hours, remaining = divmod(seconds, 3600)
    minutes, seconds = divmod(remaining, 60)
    parts = []
    if hours:
        parts.append(f"{hours} hr")
    if minutes:
        parts.append(f"{minutes} min")
    if seconds or not parts:
        parts.append(f"{seconds} sec")
    return " ".join(parts)


def _pdf_available(job):
    try:
        report_file, _filename = open_job_report(job.pk)
    except ArtifactUnavailable:
        return False
    report_file.close()
    return True
