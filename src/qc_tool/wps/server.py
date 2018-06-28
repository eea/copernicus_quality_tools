#!/usr/bin/env python3

# This module is contracted version of <https://github.com/geopython/pywps-flask/blob/master/demo.py>.


import json
import re
from pathlib import Path

import flask
import pywps
from pywps import Service
from pywps.configuration import get_config_value

from qc_tool.common import CONFIG
from qc_tool.common import WPS_DIR
from qc_tool.wps.process import CopSleep
from qc_tool.wps.process import RunChecks
from qc_tool.wps.registry import load_all_check_functions


app = flask.Flask(__name__)

service = None


@app.route("/")
def hello():
    return flask.Response("It works!", content_type="text/plain")

@app.route('/wps', methods=['GET', 'POST'])
def wps():
    return service


def run_server():
    global service

    wps_config = pywps.configuration.CONFIG
    wps_config.set("server", "url", CONFIG["wps_url"])
    wps_config.set("server", "outputurl", CONFIG["wps_output_url"])

    wps_output_dir = CONFIG["wps_output_dir"]
    wps_output_dir.mkdir(exist_ok=True, parents=True)
    wps_config.set("server", "outputpath", str(wps_output_dir))

    wps_work_dir = WPS_DIR.joinpath("work")
    wps_work_dir.mkdir(exist_ok=True, parents=True)
    wps_config.set("server", "workdir", str(wps_work_dir))

    wps_log_dir = WPS_DIR.joinpath("log")
    wps_log_dir.mkdir(exist_ok=True, parents=True)
    wps_config.set("logging", "file", str(wps_log_dir.joinpath("pywps.log")))

    load_all_check_functions()

    processes = [CopSleep(), RunChecks()]
    config_filepaths = [str(Path(__file__).with_name("pywps.cfg"))]
    # FIXME:
    # The same time service reads configuration it opens log file immediately.
    # So we can not adjust the logging later.
    # Moreover, the service fails immediately while the path to log file
    # specified in config file does not even exist yet.
    service = Service(processes, [])
    app.run(threaded=True, host="0.0.0.0", port=CONFIG["wps_port"])


if __name__ == "__main__":
    run_server()
