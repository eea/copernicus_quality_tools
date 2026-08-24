#!/usr/bin/env python3


import json
import logging
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from socket import gethostname
from subprocess import PIPE
from subprocess import Popen
from time import sleep
from threading import Event
from threading import Thread
from urllib.request import HTTPRedirectHandler
from urllib.request import ProxyHandler
from urllib.request import Request
from urllib.request import build_opener
from uuid import uuid4

import bottle

from qc_tool.common import CONFIG
from qc_tool.common import auth_worker
from qc_tool.common import get_worker_token
from qc_tool.worker_auth import build_worker_authorization
from qc_tool.worker_auth import parse_worker_authorization
from qc_tool.worker_auth import WORKER_AUTHENTICATE_HEADER
from qc_tool.worker.jobs import read_pulled_job


QUERY_INTERVAL = 10
WORKER_REQUEST_TIMEOUT_SECONDS = 30
MAX_WORKER_SLOTS = 128


log = logging.getLogger(__name__)


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
        self.max_slots = max_slots

    @property
    def free_slots(self):
        return self.max_slots - len(self._job_table)

    def get_table_json(self):
        info = []
        for job_uuid, created in self._job_table.items():
            info.append({"uuid": job_uuid, "created": created.isoformat()})
        return info

    def get_job_json(self, job_uuid):
        created = self._job_table.get(job_uuid, None)
        if created is None:
            info = None
        else:
            info = {"uuid": job_uuid, "created": created.isoformat()}
        return info

    def put(self, job_uuid):
        self._job_table[job_uuid] = datetime.utcnow()

    def rm(self, job_uuid):
        self._job_table.pop(job_uuid, None)

job_table = JobTable()


class Scheduler():
    def __init__(self, query_url):
        self.query_url = query_url
        self.query_interval = QUERY_INTERVAL

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
        t = Thread(target=self.run, name="scheduler", daemon=True)
        t.start()
        log.info("Scheduler has started.")

    def run(self):
        while True:
            while job_table.free_slots > 0:
                # Query a new job.
                log.debug("Querying a new job...")
                query_time = datetime.utcnow()
                job_args = self.pull_job()
                if job_args is None:
                    log.debug("Got no new job.")
                    break
                log.info(
                    "Got job %s.",
                    job_args.get("job_uuid", "<unknown>"),
                )

                # Run the new job.
                job_controller = JobController(job_args)
                job_controller.start()
            sleep(self.query_interval)


class JobController():
    def __init__(self, job_args):
        self.job_args = job_args

    def start(self):
        put_event = Event()
        name = self.job_args["job_uuid"].lower().replace("-", "")
        t = Thread(target=self.run, name=name, args=(put_event,))
        t.start()

        # We need to wait until the controller thread acknowledges the job has been put into job table.
        # Otherwise the scheduler may pull a new job even if all slots have already been spent.
        put_event.wait()

    def run(self, put_event):
        job_uuid = self.job_args.get("job_uuid", "<invalid>")
        try:
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
                process = Popen(
                    args=args,
                    stdin=PIPE if s3_secret is not None else None,
                    stdout=stdout_f,
                    stderr=stdout_f,
                )
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
            # TODO Here the updated job status could be sent to the frontend DB.
            job_table.rm(job_uuid)
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
