#!/usr/bin/env python3

# This module is contracted version of <https://github.com/geopython/pywps-flask/blob/master/demo.py>.


import json
import os
import re
import sys
from argparse import ArgumentParser
from os import environ
from os.path import normpath
from pathlib import Path

import flask
import pywps
from pywps import Service
from pywps.configuration import get_config_value

from qc_tool.wps.process import CopSleep
from qc_tool.wps.process import RunChecks
from qc_tool.wps.registry import get_check_function
from qc_tool.wps.registry import get_idents


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
    product_type_regex = re.compile(r"[a-z].*\.json$")
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

@app.route("/check_functions")
def check_functions():
    function_dict = {ident: get_check_function(ident).description for ident in get_idents()}
    return flask.Response(json.dumps(function_dict), content_type="application/json")

@app.route("/status_document_urls")
def status_document_urls():
    status_document_regex = re.compile(r"[a-z0-9-]{36}\.xml")
    wps_output_dir = Path(get_config_value("server", "outputpath"))
    wps_output_url = get_config_value("server", "outputurl")
    # FIXME: compose the url by dedicated functions instead of such plain way.
    status_document_urls = ["{:s}/{:s}".format(wps_output_url, path.name)
                            for path in wps_output_dir.iterdir()
                            if status_document_regex.match(path.name) is not None]
    return flask.Response(json.dumps(status_document_urls), content_type="application/json")


def run_server():
    global service

    port = int(environ["WPS_PORT"])
    wps_dir = Path(environ["WPS_DIR"])
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
    config.set("server", "url", environ["WPS_URL"])
    config.set("server", "outputurl", environ["WPS_OUTPUT_URL"])
    config.set("server", "outputpath", str(wps_output_dir))
    config.set("server", "workdir", str(wps_work_dir))
    config.set("logging", "file", str(wps_log_dir.joinpath("pywps.log")))

    app.run(threaded=True, host="0.0.0.0", port=port)


if __name__ == "__main__":
    run_server()
