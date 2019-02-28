#!/usr/bin/env python3

# This module is contracted version of <https://github.com/geopython/pywps-flask/blob/master/demo.py>.


import json
import re
from pathlib import Path

import flask
import pywps

from qc_tool.common import CONFIG
from qc_tool.wps.process import CopSleep
from qc_tool.wps.process import RunChecks


WPS_LISTEN_IP = "0.0.0.0"
WPS_LISTEN_PORT = 5000


app = flask.Flask(__name__)

service = None


@app.route("/")
def hello():
    return flask.Response("It works!", content_type="text/plain")

@app.route('/wps', methods=['GET', 'POST'])
def wps():
    return service

@app.route("/output/<path:filepath>", methods=["GET"])
def get_output_file(filepath):
    return flask.send_from_directory(str(CONFIG["wps_output_dir"]), filepath)


def run_server():
    import socket

    global service

    wps_config = pywps.configuration.CONFIG

    wps_hostname = socket.gethostname()
    wps_ip_addr = socket.gethostbyname(wps_hostname)
    wps_config.set("server", "url", "http://{:s}:{:d}/wps".format(wps_hostname, WPS_LISTEN_PORT))
    wps_config.set("server", "outputurl", "http://{:s}:{:d}/output".format(wps_ip_addr, WPS_LISTEN_PORT))
    wps_config.set("server", "maxprocesses", str(CONFIG["wps_queue_length"]))
    wps_config.set("server", "parallelprocesses", str(CONFIG["wps_parallel_processes"]))
    wps_config.set("logging", "database", CONFIG["wps_dblog_url"])

    wps_output_dir = CONFIG["wps_output_dir"]
    wps_output_dir.mkdir(exist_ok=True, parents=True)
    wps_config.set("server", "outputpath", str(wps_output_dir))

    wps_work_dir = CONFIG["wps_dir"].joinpath("work")
    wps_work_dir.mkdir(exist_ok=True, parents=True)
    wps_config.set("server", "workdir", str(wps_work_dir))

    wps_log_dir = CONFIG["wps_dir"].joinpath("log")
    wps_log_dir.mkdir(exist_ok=True, parents=True)
    wps_config.set("logging", "file", str(wps_log_dir.joinpath("pywps.log")))

    processes = [CopSleep(), RunChecks()]
    config_filepaths = [str(Path(__file__).with_name("pywps.cfg"))]
    # FIXME:
    # The same time service reads configuration it opens log file immediately.
    # So we can not adjust the logging later.
    # Moreover, the service fails immediately while the path to log file
    # specified in config file does not even exist yet.
    service = pywps.Service(processes, [])
    app.run(threaded=True, host=WPS_LISTEN_IP, port=WPS_LISTEN_PORT)


if __name__ == "__main__":
    run_server()
