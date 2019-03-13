#!/usr/bin/env python3


import json
import logging
from datetime import datetime
from subprocess import Popen
from time import sleep
from threading import Thread
from traceback import format_exc
from urllib.request import Request
from urllib.request import urlopen
from uuid import uuid4

import bottle

from qc_tool.common import CONFIG


SERVER_PORT = 8000
SERVER_ADDR = "0.0.0.0"
QUERY_INTERVAL = 10


log = logging.getLogger(__name__)


@bottle.route("/info")
def info():
    """Returns the job table."""
    return str(job_table.get_table_info())

@bottle.route("/info")
def info():
    """Returns the job table."""
    return str(job_table.get_table_info())

@bottle.route("/job/<job_uuid>")
def job(job_uuid):
    """Tells if the job is being run, i.e. is in job table."""
    return str(job_table.get_job_info(job_uuid))


class JobTable():
    def __init__(self, max_slots=1):
        self.job_items = {}
        self.max_slots = max_slots

    @property
    def free_slots(self):
        return self.max_slots - len(self.job_items)

    def get_table_info(self):
        info = [(job_uuid, job_start_time) for job_uuid, job_start_time in self.job_items.items()]
        return info

    def get_job_info(self, job_uuid):
        job_info = self.job_items.get(job_uuid, None)
        return str(job_info)

    def add(self, job_uuid):
        self.job_items[job_uuid] = datetime.now()

    def rm(self, job_uuid):
        del self.job_items[job_uuid]

    def is_running(self, job_uuid):
        return job_uuid in self.job_items

job_table = JobTable()


class Scheduler():
    def __init__(self, query_url):
        self.query_url = query_url
        self.query_interval = QUERY_INTERVAL

    def pull_job(self):
        job_args = None
        try:
            data = urlopen(Request(self.query_url)).read().strip()
            log.debug("Pulled job, data={:s}".format(repr(data)))
            job_args = json.loads(data)
        except:
            log.debug(format_exc())
        return job_args

    def start(self):
        log.debug("Starting scheduler...")
        t = Thread(target=self.run, daemon=True)
        t.start()
        log.info("Scheduler has started.")

    def run(self):
        while True:
            while job_table.free_slots > 0:
                # Query a new job.
                log.debug("Querying a new job...")
                query_time = datetime.now()
                job_args = self.pull_job()
                if job_args is None:
                    log.debug("Got no new job.")
                    break
                log.info("Got a new job {:s}.".format(repr(job_args)))

                # Run the new job.
                job_controller = JobController(job_table, job_args)
                job_controller.start()
            sleep(self.query_interval)


class JobController():
    def __init__(self, job_args):
        self.job_args = job_args

    def start(self):
        t = Thread(target=self.run)
        t.start()
        # FIXME:
        # Let the controller thread add the job item to job table.
        # However, it should be ensured that this thread continues only after the job item is really added to the table.
        job_table.add(self.job_args["job_uuid"])
        log.info("Started controller for job {:s}.".format(self.job_args["job_uuid"]))
    
    def run(self):
        try:
            args = ["python3",
                    "-m", "qc_tool.worker.cmd",
                    "--job-uuid", self.job_args["job_uuid"],
                    "--product", self.job_args["product_ident"]]
            if self.job_args["skip_steps"] is not None:
                args += ["--skip-steps", self.job_args["skip_steps"]]
            args += [self.job_args["username"],
                     self.job_args["filename"]]
            log.debug(repr(args))
            process = Popen(args=args)
            log.debug("Started job uuid={:s}, pid={:d}.".format(self.job_args["job_uuid"], process.pid))
            process.wait()
        except:
            log.error(format_exc())
        finally:
            job_table.rm(self.job_args["job_uuid"])
            log.info("Closing controller for job {:s}.".format(self.job_args["job_uuid"]))

            
def main():
    # Set up logging.
    log.setLevel(logging.DEBUG)
    log.addHandler(logging.StreamHandler())

    # Run the scheduler.
    scheduler = Scheduler(CONFIG["pull_job_url"])
    bottle.default_app().scheduler = scheduler
    scheduler.start()

    # Run the web.
    bottle.run(host=SERVER_ADDR, port=SERVER_PORT)


if __name__ == "__main__":
    # FIXME:
    # Wait for postgresql service.
    # Or remove the sleep after qc_tool_postgis is embedded in qc_tool_worker.
    sleep(10)

    main()
