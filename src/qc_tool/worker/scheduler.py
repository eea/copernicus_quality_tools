#!/usr/bin/env python3


import json
import logging
import os
import signal
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from socket import gethostname
from subprocess import PIPE
from subprocess import Popen
from time import monotonic, sleep
from threading import Event
from threading import RLock
from threading import Thread
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler
from urllib.request import ProxyHandler
from urllib.request import Request
from urllib.request import build_opener

import bottle

from qc_tool.common import CONFIG
from qc_tool.common import auth_worker
from qc_tool.common import get_worker_token
from qc_tool.maintenance.protocol import decode_message
from qc_tool.maintenance.protocol import MAX_MESSAGE_BYTES as MAX_MAINTENANCE_BYTES
from qc_tool.maintenance.protocol import parse_command
from qc_tool.maintenance.protocol import parse_state as _maintenance_payload
from qc_tool.worker_auth import build_worker_authorization
from qc_tool.worker_auth import parse_worker_authorization
from qc_tool.worker_auth import WORKER_AUTHENTICATE_HEADER
from qc_tool.worker.jobs import read_pulled_job


QUERY_INTERVAL = 10
WORKER_REQUEST_TIMEOUT_SECONDS = 30
MAX_WORKER_SLOTS = 128
TERMINATION_GRACE_SECONDS = 5


log = logging.getLogger(__name__)


class WorkerMaintenance:
    """Fence claims and process launches until the frontend grants admission.

    Generation numbers prevent delayed HTTP responses from reopening a worker
    after a newer administrator command. A failed poll adds a local pause but
    does not invent a frontend generation.
    """

    def __init__(self):
        self.lock = RLock()
        self._enabled = True
        self._generation = -1
        self._available = False
        self._pulls = 0
        self._controllers = set()

    @property
    def paused(self):
        with self.lock:
            return self._enabled or not self._available

    def snapshot(self):
        with self.lock:
            return {
                "enabled": self.paused,
                "generation": max(self._generation, 0),
                "quiescent": not self._pulls and not self._controllers,
            }

    def update(self, enabled, generation):
        _maintenance_payload({"enabled": enabled, "generation": generation})
        with self.lock:
            if generation < self._generation:
                return self.snapshot()
            # One generation identifies one authoritative state. Conflicting
            # same-generation commands cannot reopen a paused worker.
            if generation == self._generation and enabled != self._enabled:
                return self.snapshot()
            self._generation = generation
            self._enabled = enabled
            self._available = True
            if enabled:
                for controller in tuple(self._controllers):
                    controller.request_stop()
            return self.snapshot()

    def unavailable(self):
        with self.lock:
            self._available = False
            for controller in tuple(self._controllers):
                controller.request_stop()

    def begin_pull(self):
        with self.lock:
            if self.paused:
                return False
            self._pulls += 1
            return True

    def finish_pull(self):
        with self.lock:
            self._pulls -= 1

    def register(self, controller):
        with self.lock:
            if self.paused:
                return False
            self._controllers.add(controller)
            return True

    def unregister(self, controller):
        with self.lock:
            self._controllers.discard(controller)


maintenance = WorkerMaintenance()


def _process_group_exists(process_group):
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    # Permission failures must never be interpreted as a stopped group.
    except PermissionError:
        return True
    return True


class _RejectRedirects(HTTPRedirectHandler):
    """Do not forward worker credentials to a redirect destination."""

    def redirect_request(
        self,
        request,
        file_pointer,
        code,
        message,
        headers,
        new_url,
    ):
        return None


# Internal worker credentials must not be forwarded through ambient
# HTTP(S)_PROXY environment configuration.
_worker_url_opener = build_opener(ProxyHandler({}), _RejectRedirects())


@bottle.hook("before_request")
def require_worker_authentication():
    """Protect worker state while retaining one non-sensitive health route."""

    if bottle.request.path == "/health":
        return
    token = parse_worker_authorization(
        bottle.request.headers.get("Authorization")
    )
    if token is None or not auth_worker(token):
        raise bottle.HTTPError(
            401,
            "Authentication required.",
            **{
                "WWW-Authenticate": WORKER_AUTHENTICATE_HEADER,
                "Cache-Control": "no-store, private",
            }
        )


@bottle.get("/health")
def get_health():
    """Return no job data and require no shared secret for health checks."""

    bottle.response.content_type = "application/json"
    active_scheduler = getattr(bottle.default_app(), "scheduler", None)
    if active_scheduler is not None and not active_scheduler.healthy:
        bottle.response.status = 503
        return json.dumps({"status": "unavailable"})
    return json.dumps({"status": "ok"})


@bottle.error(401)
def worker_authentication_error(_error):
    """Keep machine-authentication failures status-only and cache-safe."""

    bottle.response.content_type = "text/plain"
    return ""


@bottle.get("/table.json")
def get_table():
    """Gets the whole job table."""
    bottle.response.content_type = "application/json"
    return json.dumps(job_table.get_table_json())

@bottle.get("/jobs/<job_uuid>.json")
def get_job(job_uuid):
    """Gets the job info.

    This function may be used for checking the job is still running."""
    bottle.response.content_type = "application/json"
    return json.dumps(job_table.get_job_json(job_uuid))

@bottle.get("/max_slots.json")
def get_max_slots():
    bottle.response.content_type = "application/json"
    return json.dumps(job_table.max_slots)


@bottle.put("/maintenance")
def set_maintenance():
    """Accept only bounded, authenticated controller commands."""

    if not 0 <= bottle.request.content_length <= MAX_MAINTENANCE_BYTES:
        bottle.abort(400, "Invalid maintenance state.")
    body = bottle.request.body.read(MAX_MAINTENANCE_BYTES + 1)
    try:
        enabled, generation = parse_command(decode_message(body))
    except (UnicodeDecodeError, ValueError):
        bottle.abort(400, "Invalid maintenance state.")
    bottle.response.content_type = "application/json"
    bottle.response.set_header("Cache-Control", "no-store, private")
    return json.dumps(maintenance.update(enabled, generation))

@bottle.put("/max_slots")
def set_max_slots():
    max_slots = bottle.request.json
    if (
        not isinstance(max_slots, int)
        or isinstance(max_slots, bool)
        or not 1 <= max_slots <= MAX_WORKER_SLOTS
    ):
        bottle.abort(
            400,
            "Argument must be an integer between 1 and {:d}.".format(
                MAX_WORKER_SLOTS
            ),
        )
    job_table.max_slots = max_slots
    return


class JobTable():
    def __init__(self, max_slots=1):
        self._job_table = {}
        self._lock = RLock()
        self.max_slots = max_slots

    @property
    def free_slots(self):
        with self._lock:
            return self.max_slots - len(self._job_table)

    def get_table_json(self):
        with self._lock:
            return [
                {"uuid": job_uuid, "created": created.isoformat()}
                for job_uuid, created in self._job_table.items()
            ]

    def get_job_json(self, job_uuid):
        with self._lock:
            created = self._job_table.get(job_uuid, None)
        if created is None:
            info = None
        else:
            info = {"uuid": job_uuid, "created": created.isoformat()}
        return info

    def put(self, job_uuid):
        with self._lock:
            self._job_table[job_uuid] = datetime.utcnow()

    def rm(self, job_uuid):
        with self._lock:
            self._job_table.pop(job_uuid, None)

job_table = JobTable()


class Scheduler():
    def __init__(self, query_url):
        self.query_url = query_url
        parsed = urlsplit(query_url)
        parent_path = parsed.path.rsplit("/", 1)[0]
        self.maintenance_url = urlunsplit(
            (parsed.scheme, parsed.netloc, parent_path + "/worker_maintenance", "", "")
        )
        self.query_interval = QUERY_INTERVAL
        self._thread = None
        self._failed = False

    @property
    def healthy(self):
        return (
            not self._failed
            and self._thread is not None
            and self._thread.is_alive()
        )

    def refresh_maintenance(self):
        try:
            request = Request(
                self.maintenance_url,
                headers={
                    "Accept": "application/json",
                    "Authorization": build_worker_authorization(get_worker_token()),
                },
                method="POST",
            )
            with _worker_url_opener.open(
                request, timeout=WORKER_REQUEST_TIMEOUT_SECONDS,
            ) as response:
                body = response.read(MAX_MAINTENANCE_BYTES + 1)
                enabled, generation = _maintenance_payload(decode_message(body))
            maintenance.update(enabled, generation)
        except Exception as exc:
            maintenance.unavailable()
            log.warning("Maintenance query failed safely (%s).", type(exc).__name__)
        return maintenance.snapshot()

    def pull_job(self):
        job_args = None
        try:
            # Keep credentials outside the URL so they do not end up in
            # access logs, proxy logs, or monitoring traces.
            token = get_worker_token()
            request = Request(
                self.query_url,
                headers={
                    "Accept": "application/json",
                    "Authorization": build_worker_authorization(token),
                },
                method="POST",
            )

            with _worker_url_opener.open(
                request,
                timeout=WORKER_REQUEST_TIMEOUT_SECONDS,
            ) as response:
                job_args = read_pulled_job(response)
        except Exception as exc:
            # Do not include response bodies or credentials in scheduler logs.
            log.warning(
                "The pull-job request failed safely (%s).",
                type(exc).__name__,
            )
        return job_args

    def start(self):
        self._thread = Thread(target=self._run_guarded, name="scheduler", daemon=True)
        try:
            self._thread.start()
        except Exception:
            self._failed = True
            maintenance.unavailable()
            raise
        log.info("Scheduler has started.")

    def _run_guarded(self):
        """A dead scheduling loop must close admission and fail its probe."""
        try:
            self.run()
            raise RuntimeError("The scheduler loop exited unexpectedly.")
        except BaseException:
            self._failed = True
            maintenance.unavailable()
            log.exception("Scheduler stopped unexpectedly; worker admission is closed.")

    def _claim_batch(self, poll_deadline):
        """Bound claim attempts by time and capacity, without idle throttling.

        Short jobs can finish while the batch is claiming more work. Limiting
        this batch makes another authority poll unavoidable under continuous
        load. A productive batch can poll again immediately instead of waiting
        an extra interval before filling a free slot.
        """
        batch_limit = max(1, job_table.max_slots)
        for _ in range(batch_limit):
            if (
                job_table.free_slots <= 0
                or monotonic() >= poll_deadline
                or not maintenance.begin_pull()
            ):
                return False
            try:
                log.debug("Querying a new job...")
                job_args = self.pull_job()
                if job_args is None:
                    log.debug("Got no new job.")
                    return False
                log.info("Got job %s.", job_args.get("job_uuid", "<unknown>"))
                # Recheck admission after the network call. A pause during
                # an in-flight claim can never launch its response.
                if not JobController(job_args).start():
                    return False
            finally:
                maintenance.finish_pull()
        return job_table.free_slots > 0 and not maintenance.paused

    def run(self):
        while True:
            # Poll even when every slot is occupied: active jobs must react to
            # maintenance and loss of their admission authority.
            self.refresh_maintenance()
            poll_deadline = monotonic() + self.query_interval
            if self._claim_batch(poll_deadline):
                continue
            remaining = poll_deadline - monotonic()
            if remaining > 0:
                sleep(remaining)


class JobController():
    def __init__(self, job_args):
        self.job_args = job_args
        self.process = None
        self._registered = False
        self._stop_event = Event()
        self._stop_thread = None

    def start(self):
        if not maintenance.register(self):
            return False
        self._registered = True
        put_event = Event()
        name = self.job_args["job_uuid"].lower().replace("-", "")
        t = Thread(target=self.run, name=name, args=(put_event,))
        try:
            t.start()
        except Exception:
            maintenance.unregister(self)
            raise

        # We need to wait until the controller thread acknowledges the job has been put into job table.
        # Otherwise the scheduler may pull a new job even if all slots have already been spent.
        put_event.wait()
        return True

    def request_stop(self):
        """Fence a pending launch and terminate the complete validator group."""

        self._stop_event.set()
        # Called while holding maintenance.lock, also used around Popen.
        if self.process is not None and self._stop_thread is None:
            self._stop_thread = Thread(target=self._terminate_group, daemon=True)
            self._stop_thread.start()

    def _terminate_group(self):
        process_group = self.process.pid
        try:
            os.killpg(process_group, signal.SIGTERM)
        except ProcessLookupError:
            return
        except PermissionError:
            log.error("Cannot terminate validator process group; worker remains non-quiescent.")
            return
        deadline = monotonic() + TERMINATION_GRACE_SECONDS
        while _process_group_exists(process_group) and monotonic() < deadline:
            self.process.poll()  # Reap an exited group leader while checking descendants.
            sleep(0.05)
        if _process_group_exists(process_group):
            try:
                os.killpg(process_group, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError:
                log.error("Cannot kill validator process group; worker remains non-quiescent.")

    def run(self, put_event):
        job_uuid = self.job_args.get("job_uuid", "<invalid>")
        try:
            if not self._registered:
                if not maintenance.register(self):
                    return
                self._registered = True
            log.info("Controller for job %s has started.", job_uuid)
            job_table.put(job_uuid)
            put_event.set()
            args = ["/usr/bin/time",
                    "python3",
                    "-m", "qc_tool.worker.cmd",
                    "--job-uuid", self.job_args["job_uuid"],
                    "--product", self.job_args["product_ident"]]
            if self.job_args["skip_steps"] is not None:
                args += ["--skip-steps", self.job_args["skip_steps"]]
            args += [self.job_args["username"],
                     self.job_args["filename"]]
            if self.job_args.get("s3_host") is not None:
                args += ["--s3-host", self.job_args["s3_host"]]
                args += ["--s3-access-key", self.job_args["s3_access_key"]]
                # Never place secrets in argv: process command lines are often
                # visible to other processes and infrastructure diagnostics.
                args += ["--s3-secret-key-stdin"]
                args += ["--s3-bucketname", self.job_args["s3_bucketname"]]
                args += ["--s3-key-prefix", self.job_args["s3_key_prefix"]]
            log.debug(
                "Launching job %s for product %s.",
                job_uuid,
                self.job_args["product_ident"],
            )
            stdout_filepath = CONFIG["work_dir"].joinpath("job.{:s}.stdout".format(self.job_args["job_uuid"]))
            log.debug("The job has stdout and stderr redirected to %s.".format(stdout_filepath))
            with open(stdout_filepath, "a") as stdout_f:
                stdout_f.write("\n\n")
                stdout_f.write("The job {:s} has started at {:s}+00:00.\n".format(self.job_args["job_uuid"], datetime.utcnow().isoformat()))
                stdout_f.write("stdout and stderr of the job is redirected to this file.\n".format(self.job_args["job_uuid"]))
                stdout_f.write("\n")
                stdout_f.flush()
                s3_secret = self.job_args.get("s3_secret_key")
                with maintenance.lock:
                    if maintenance.paused or self._stop_event.is_set():
                        return
                    process = Popen(
                        args=args,
                        stdin=PIPE if s3_secret is not None else None,
                        stdout=stdout_f,
                        stderr=stdout_f,
                        start_new_session=True,
                    )
                    self.process = process
                log.info("Started job with pid={:d}.".format(process.pid))
                if s3_secret is None:
                    process.wait()
                else:
                    process.communicate(input=s3_secret.encode("utf-8"))
                log.info("Job has exited with code={:d}.".format(process.returncode))
                stdout_f.write("\n\n")
                stdout_f.write("The job {:s} has exited with code {:d}.\n".format(self.job_args["job_uuid"], process.returncode))
        except Exception:
            log.exception("Controller for job %s failed.", job_uuid)
        finally:
            # Never leave Scheduler.start() waiting if malformed input fails
            # before the controller can be registered.
            put_event.set()
            if self.process is not None:
                # Reap the direct child and account for descendants, including
                # subprocesses left alive after their validator parent exits.
                if _process_group_exists(self.process.pid):
                    with maintenance.lock:
                        self.request_stop()
                self.process.wait()
                if self._stop_thread is not None:
                    self._stop_thread.join()
                while _process_group_exists(self.process.pid):
                    # An unreaped descendant or failed kill keeps readiness
                    # false. Never certify quiescence from parent exit alone.
                    sleep(0.1)
            # TODO Here the updated job status could be sent to the frontend DB.
            job_table.rm(job_uuid)
            maintenance.unregister(self)
            log.info("Closing controller.")

def init_logging():
    log_dir = CONFIG["work_dir"]
    log_dir.mkdir(parents=True, exist_ok=True)
    log_filepath = log_dir.joinpath("scheduler.{:s}.log".format(gethostname()))
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(fmt="{message}", style="{"))
    console_handler.setLevel(logging.ERROR)
    file_handler = TimedRotatingFileHandler(log_filepath, when="D", backupCount=14)
    file_handler.setFormatter(logging.Formatter(fmt="{asctime} {levelname} {threadName} {filename}:{lineno} {message}", style="{"))
    file_handler.setLevel(logging.DEBUG)
    root_log = logging.getLogger()
    root_log.addHandler(console_handler)
    root_log.addHandler(file_handler)
    log.info("Logging of the scheduler has been started.")

def main():
    init_logging()

    # Run the scheduler.
    scheduler = Scheduler(CONFIG["pull_job_url"])
    bottle.default_app().scheduler = scheduler
    log.debug("Starting scheduler...")
    scheduler.start()

    # Run the web.
    log.debug("Starting web server...")
    bottle.run(host=CONFIG["worker_addr"], port=CONFIG["worker_port"])


if __name__ == "__main__":
    # FIXME:
    # Wait for postgresql service.
    # Or remove the sleep after qc_tool_postgis is embedded in qc_tool_worker.
    sleep(10)

    main()
