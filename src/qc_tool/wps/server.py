#!/usr/bin/env python3

# This module is contracted version of <https://github.com/geopython/pywps-flask/blob/master/demo.py>.


import json
import os
import re
import sys
from argparse import ArgumentParser
from os.path import normpath
from pathlib import Path

import flask
import pywps
from pywps import Service

from qc_tool.wps.process import CopSleep
from qc_tool.wps.process import RunChecks


QC_TOOL_HOME = Path(normpath(str(Path(__file__).joinpath("../../../.."))))
PRODUCT_TYPES_DIR = QC_TOOL_HOME.joinpath("product_types")


app = flask.Flask(__name__)

service = None


@app.route("/")
def hello():
    return flask.Response("It works!", content_type="text/plain")

@app.route('/wps', methods=['GET', 'POST'])
def wps():
    return service

@app.route("/output/<filename>")
def outputfile(filename):
    wps_output_dir = Path(pywps.configuration.get_config_value("server", "outputpath"))
    # FIXME: ensure the resulting path can not be rerouted to other tree by using "..".
    filepath = wps_output_dir.joinpath(filename)
    if filepath.is_file():
        file_bytes = filepath.read_bytes()
        if ".xml" == filepath.suffix:
            content_type = 'text/xml'
        else:
            content_type = None
        return flask.Response(file_bytes, content_type=content_type)
    else:
        flask.abort(404)

@app.route("/product_types")
def product_types():
    product_type_regex = re.compile("[a-z].*\.json$")
    product_type_filepaths = [path
                              for path in PRODUCT_TYPES_DIR.iterdir()
                              if product_type_regex.match(path.name) is not None]
    product_types = {}
    for filepath in product_type_filepaths:
        product_type_name = filepath.stem
        product_type_definition = filepath.read_text()
        product_type_definition = json.loads(product_type_definition)
        product_types[product_type_name] = product_type_definition
    return flask.Response(json.dumps(product_types), content_type="application/json")

def run_server():
    global service

    host = os.environ.get("WPS_HOST", "127.0.0.1")
    port = int(os.environ.get("WPS_PORT", "5300"))
    wps_dir = Path(os.environ.get("WPS_DIR", "/mnt/wps"))
    wps_output_dir = wps_dir.joinpath("output")
    wps_output_dir.mkdir(exist_ok=True)
    wps_work_dir = wps_dir.joinpath("work")
    wps_work_dir.mkdir(exist_ok=True)
    wps_log_dir = wps_dir.joinpath("log")
    wps_log_dir.mkdir(exist_ok=True)

    processes = [CopSleep(), RunChecks()]
    config_filepaths = [str(Path(__file__).with_name("pywps.cfg"))]
    # FIXME:
    # The same time service reads configuration it opens log file immediately.
    # So we can not adjust the logging later.
    # Moreover, the service fails immediately while the path to log file
    # specified in config file does not even exist yet.
    service = Service(processes, [])

    config = pywps.configuration.CONFIG
    config.set("server", "url", "http://{:s}:{:d}/wps".format(host, port))
    config.set("server", "outputurl", "http://{:s}:{:d}/output".format(host, port))
    config.set("server", "outputpath", str(wps_output_dir))
    config.set("server", "workdir", str(wps_work_dir))
    config.set("logging", "file", str(wps_log_dir.joinpath("pywps.log")))

    app.run(threaded=True, host=host, port=port)


if __name__ == "__main__":
    run_server()
