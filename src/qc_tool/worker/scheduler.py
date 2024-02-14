#!/usr/bin/env python3


import json
import logging
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from socket import gethostname
from subprocess import Popen
from time import sleep
from threading import Event
from threading import Thread
from traceback import format_exc
from urllib.parse import urlencode
from urllib.parse import urlsplit
from urllib.parse import urlunsplit
from urllib.request import Request
from urllib.request import urlopen
from uuid import uuid4

import bottle

from qc_tool.common import CONFIG
from qc_tool.common import get_worker_token
from qc_tool.common import WORKER_PORT
from qc_tool.common import WORKER_ADDR


QUERY_INTERVAL = 10


log = logging.getLogger(__name__)


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
    if not isinstance(max_slots, int):
        bottle.abort(400, "Argument must be an integer.")
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
        del self._job_table[job_uuid]

job_table = JobTable()


class Scheduler():
    def __init__(self, query_url):
        self.query_url = query_url
        self.query_interval = QUERY_INTERVAL

    def pull_job(self):
        job_args = None
        try:
            # Get worker token and inject it into url.
            token = get_worker_token()
            url = list(urlsplit(self.query_url))
            url[3] = urlencode({"token": token})
            url = urlunsplit(url)

            # Pull job from frontend.
            data = urlopen(Request(url)).read().strip()
            log.debug("Pulled job data: {:s}".format(repr(data)))
            job_args = json.loads(data)
        except:
            log.debug(format_exc())
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
                log.info("Got a new job: {:s}.".format(repr(job_args)))

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
        log.info("Controller for the job {:s} has been started.".format(self.job_args["job_uuid"]))
        try:
            job_table.put(self.job_args["job_uuid"])
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
                args += ["--s3-secret-key", self.job_args["s3_secret_key"]]
                args += ["--s3-bucketname", self.job_args["s3_bucketname"]]
                args += ["--s3-key-prefix", self.job_args["s3_key_prefix"]]
            log.debug("Launching a new job: {:s}.".format(repr(args)))
            stdout_filepath = CONFIG["work_dir"].joinpath("job.{:s}.stdout".format(self.job_args["job_uuid"]))
            log.debug("The job has stdout and stderr redirected to %s.".format(stdout_filepath))
            with open(stdout_filepath, "a") as stdout_f:
                stdout_f.write("\n\n")
                stdout_f.write("The job {:s} has started at {:s}+00:00.\n".format(self.job_args["job_uuid"], datetime.utcnow()))
                stdout_f.write("stdout and stderr of the job is redirected to this file.\n".format(self.job_args["job_uuid"]))
                stdout_f.write("\n")
                stdout_f.flush()
                process = Popen(args=args, stdout=stdout_f, stderr=stdout_f)
                log.info("Started job with pid={:d}.".format(process.pid))
                process.wait()
                log.info("Job has exited with code={:d}.".format(process.returncode))
                stdout_f.write("\n\n")
                stdout_f.write("The job {:s} has exited with code {:d}.\n".format(self.job_args["job_uuid"], process.returncode))
        except:
            log.error(format_exc())
        finally:
            job_table.rm(self.job_args["job_uuid"])
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
    bottle.run(host=WORKER_ADDR, port=WORKER_PORT)


if __name__ == "__main__":
    # FIXME:
    # Wait for postgresql service.
    # Or remove the sleep after qc_tool_postgis is embedded in qc_tool_worker.
    sleep(10)

    main()
