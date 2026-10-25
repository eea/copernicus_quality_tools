"""Serialize administrator actions and require positive worker acknowledgments."""

from concurrent.futures import ThreadPoolExecutor, wait
import logging
from datetime import datetime, timezone

from django.conf import settings
from django.db import DatabaseError, transaction

from qc_tool.common import CONFIG, JOB_ERROR, JOB_RUNNING, JOB_WAITING, WORKER_PORT
from qc_tool.worker_auth import InvalidWorkerUrl, worker_maintenance_url

from .state import MaintenanceBusy, MaintenanceError, file_lock, read_status, stamp, write_status
from .workers import request_worker_state as _worker_state
from .operations import require_no_operation


logger = logging.getLogger(__name__)
MAX_PROBE_WORKERS = 8
READINESS_TIMEOUT_SECONDS = 10


def _check_generation(state, expected):
    if type(expected) is not int or expected != state["generation"]:
        raise MaintenanceError("Maintenance state changed. Reload this page before trying again.")


def enable(actor, expected_generation):
    # Already-admitted uploads may finish; the durable flag refuses new work.
    with file_lock("control", blocking=False) as acquired:
        if not acquired:
            raise MaintenanceBusy("Another maintenance action is in progress. Retry shortly.")
        require_no_operation()
        state = read_status()
        _check_generation(state, expected_generation)
        if state["enabled"] and not state["environment_only"]:
            return state
        state.update(enabled=True, phase="stopping", generation=state["generation"] + (0 if state["environment_only"] else 1),
                     blockers=["Waiting for application requests and workers to stop."], readiness_checked_at="")
        stamp(state, actor)
        write_status(state)
        logger.warning("Maintenance enabled by %s (generation %s).", actor, state["generation"])
        return state


def _worker_blockers(worker_urls, state):
    if not worker_urls:
        return []
    executor = ThreadPoolExecutor(max_workers=min(MAX_PROBE_WORKERS, len(worker_urls)), thread_name_prefix="maintenance-probe")
    try:
        futures = {url: executor.submit(_worker_state, url, state) for url in worker_urls}
        done, _ = wait(futures.values(), timeout=READINESS_TIMEOUT_SECONDS)
        blockers = []
        for url, future in futures.items():
            if future not in done:
                blockers.append("Worker {} did not acknowledge before the readiness deadline.".format(url))
                continue
            try:
                quiescent = future.result()
            except Exception as exc:
                logger.warning("Worker maintenance acknowledgment unavailable (%s).", type(exc).__name__)
                blockers.append("Worker {} has not acknowledged stopping.".format(url))
            else:
                if not quiescent:
                    blockers.append("Worker {} is still stopping processes or finishing a claim.".format(url))
        return blockers
    finally:
        # A response arriving after the pass deadline cannot certify readiness.
        # Running probes own only network sockets, and each has its own hard
        # wall deadline. Cancel queued probes instead of blocking HTTP shutdown.
        executor.shutdown(wait=False, cancel_futures=True)


def _stop_jobs(jobs):
    with transaction.atomic():
        for job in jobs.order_by("delivery_id", "date_created").iterator(chunk_size=200):
            # Delivery locks, terminal metadata and projections have one owner.
            job.update_status(JOB_ERROR)


def _mark_stopping(state, message):
    state.update(phase="stopping", blockers=[message], readiness_checked_at="")
    write_status(state)


def advance(expected_generation, *, stopping_only=False):
    """Retry stopping, preserving a completed check for automatic progress.

    Explicit rechecks retain their readiness-invalidating behavior. Automatic
    progress must not revoke readiness if another request completed the same
    generation while it was in flight. Check that under the control lock, after
    validating generation and transfer ownership.
    """
    from qc_tool.frontend.dashboard.models import Job

    with file_lock("control", blocking=False) as acquired:
        if not acquired:
            raise MaintenanceBusy("Another maintenance action is in progress. Retry shortly.")
        require_no_operation()
        state = read_status()
        _check_generation(state, expected_generation)
        if not state["enabled"]:
            raise MaintenanceError("Enable maintenance before checking readiness.")
        if stopping_only and state["phase"] == "ready":
            return state
        _mark_stopping(state, "Checking application and worker readiness.")
        with file_lock("activity", blocking=False) as drained:
            blockers = []
            if not drained:
                blockers.append("Application requests or background updates are still finishing. Check again shortly.")
            worker_urls = set(state["workers"])
            try:
                running = Job.objects.filter(job_status=JOB_RUNNING)
                for url in running.values_list("worker_url", flat=True):
                    if not url:
                        continue
                    try:
                        worker_maintenance_url(url, expected_port=CONFIG.get("worker_port", WORKER_PORT))
                    except InvalidWorkerUrl:
                        blockers.append("A running job has an invalid worker address. An operator must verify and reconcile it.")
                    else:
                        worker_urls.add(url)
                if running.filter(worker_url__isnull=True).exists() or running.filter(worker_url="").exists():
                    blockers.append("A running job has no worker address. An operator must verify and reconcile it.")
            except DatabaseError:
                blockers.append("The application database is unavailable. Restore connectivity and check readiness again.")
            state["workers"] = sorted(worker_urls)
            blockers.extend(_worker_blockers(state["workers"], state))
            if not blockers and drained:
                try:
                    _stop_jobs(Job.objects.filter(job_status__in=(JOB_WAITING, JOB_RUNNING)))
                except DatabaseError:
                    blockers.append("Interrupted job history could not be saved. Restore database connectivity and check readiness again.")
                else:
                    state.update(phase="ready", readiness_checked_at=datetime.now(timezone.utc).isoformat())
            state["blockers"] = blockers
            write_status(state)
            return state


def disable(actor, expected_generation):
    with file_lock("control", blocking=False) as acquired:
        if not acquired:
            raise MaintenanceBusy("Another maintenance action is in progress. Retry shortly.")
        require_no_operation()
        state = read_status()
        _check_generation(state, expected_generation)
        if getattr(settings, "MAINTENANCE_MODE", False):
            raise MaintenanceError("The environment forces maintenance. The operator must remove MAINTENANCE_MODE first.")
        if state["phase"] != "ready":
            raise MaintenanceError("Finish stopping work before disabling maintenance.")
        state.update(enabled=False, phase="off", generation=state["generation"] + 1, blockers=[], readiness_checked_at="")
        stamp(state, actor)
        write_status(state)
        logger.warning("Maintenance disabled by %s (generation %s).", actor, state["generation"])
        return state


def retire_worker(worker_url, actor, expected_generation, *, verified_stopped=False):
    """One audited owner for explicit retirement of a verified-stopped origin."""
    from qc_tool.frontend.dashboard.models import Job

    if not worker_url or not verified_stopped:
        raise MaintenanceError("Retiring a worker requires its address and explicit verification that all its processes are stopped.")
    with file_lock("control", blocking=False) as acquired:
        if not acquired:
            raise MaintenanceBusy("Another maintenance action is in progress. Retry shortly.")
        require_no_operation()
        state = read_status()
        _check_generation(state, expected_generation)
        if not state["enabled"] or worker_url not in state["workers"]:
            raise MaintenanceError("Enable maintenance and select a registered worker before retiring it.")
        with file_lock("activity", blocking=False) as drained:
            if not drained:
                raise MaintenanceError("Application activity is still finishing. Retry shortly.")
            # Invalidate old readiness before any DB write, including failure.
            _mark_stopping(state, "Reconciling a verified-stopped worker.")
            try:
                _stop_jobs(Job.objects.filter(worker_url=worker_url, job_status=JOB_RUNNING))
            except DatabaseError as exc:
                raise MaintenanceError("Worker retirement could not be saved. Restore database connectivity and retry.") from exc
            state["workers"].remove(worker_url)
            state.update(generation=state["generation"] + 1, blockers=["Worker retired by operator. Check readiness again."])
            stamp(state, "{} retired verified-stopped worker {}".format(actor, worker_url))
            write_status(state)
            logger.warning("Worker retired by %s (generation %s).", actor, state["generation"])
            return state
