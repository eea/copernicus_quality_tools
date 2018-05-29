#!/usr/bin/env python3


import json
from pathlib import Path
from time import sleep

from pywps.app.Process import Process
from pywps.inout.inputs import LiteralInput
from pywps.inout.outputs import LiteralOutput

from qc_tool.wps.dispatch import dispatch


class CopSleep(Process):
    # There is also keywork parameter "default" in LiteralInput constructor, however it has no effect.
    INPUTS = [LiteralInput("delay", "Delay in seconds between cycles.",
                           data_type="float", min_occurs=0, max_occurs=1),
              LiteralInput("cycles", "Number of successive delays.",
                           data_type="positiveInteger", min_occurs=0, max_occurs=1),
              LiteralInput("filepath", "Local filesystem path to the product to be checked.",
                           data_type="string", min_occurs=0, max_occurs=1),
              LiteralInput("layer_name", "The name of the layer to be checked.",
                           data_type="string", min_occurs=0, max_occurs=1),
              LiteralInput("product_type_name", "The type of the product denoting group of checks to be performed.",
                           data_type="string", min_occurs=0, max_occurs=1),
              LiteralInput("exit_ok", "false if the process should fail finally.",
                           data_type="boolean", min_occurs=0, max_occurs=1)]
    OUTPUTS = [LiteralOutput("result", "Result message.", data_type="string")]

    def __init__(self):
        super().__init__(self._handler,
                         identifier="cop_sleep",
                         version="None",
                         title="Cop Sleep Process",
                         abstract="The Cop Sleep Process sleeps while updating status.",
                         inputs=self.INPUTS,
                         outputs=self.OUTPUTS,
                         store_supported=True,
                         status_supported=True)

    def _handler(self, request, response):
        # Prepare parameters.
        params = {"delay": 1.0,
                  "cycles": 0,
                  "exit_ok": True,
                  "product_type_name": None,
                  "layer_name": None,
                  "filepath": None}
        if "delay" in request.inputs:
            params["delay"] = request.inputs["delay"][0].data
        if "cycles" in request.inputs:
            params["cycles"] = request.inputs["cycles"][0].data
        if "exit_ok" in request.inputs:
            params["exit_ok"] = request.inputs["exit_ok"][0].data
        if "filepath" in request.inputs:
            params["filepath"] = Path(request.inputs["filepath"][0].data)
        if "layer_name" in request.inputs:
            params["layer_name"] = request.inputs["layer_name"][0].data
        if "product_type_name" in request.inputs:
            params["product_type_name"] = request.inputs["product_type_name"][0].data

        # Do cycles of sleeping.
        if params["cycles"] >= 1:
            for i in range(1, params["cycles"]):
                sleep(params["delay"])
                response.update_status("Cop Sleep Process is running...", int(100 / params["cycles"] * i))
            sleep(params["delay"])

        # Generate response.
        if params["exit_ok"]:
            response.outputs["result"].data = "Cop Sleep Process has finished successfully.\nParameters: {:s}".format(repr(params))
            return response
        else:
            raise Exception("Cop Sleep Process raised exception intentionally.")


class RunChecks(Process):
    # There is also keyword parameter "default" in LiteralInput constructor, however it has no effect.
    INPUTS = [LiteralInput("filepath", "Local filesystem path to the product to be checked.",
                           data_type="string", min_occurs=1, max_occurs=1),
              LiteralInput("product_type_name", "The type of the product denoting group of checks to be performed.",
                           data_type="string", min_occurs=1, max_occurs=1),
              LiteralInput("optional_check_idents", "Comma separated identifiers of optional checks to be performed.",
                           data_type="string", min_occurs=0, max_occurs=1)]
    OUTPUTS = [LiteralOutput("result", "Result of passed checks in json format.", data_type="string")]

    def __init__(self):
        super().__init__(self._handler,
                         identifier="run_checks",
                         version="None",
                         title="Run checks process",
                         abstract="Process performing qc tool checks.",
                         inputs=self.INPUTS,
                         outputs=self.OUTPUTS,
                         store_supported=True,
                         status_supported=True)

    def _handler(self, request, response):
        # Prepare parameters.
        filepath = Path(request.inputs["filepath"][0].data)
        product_type_name = request.inputs["product_type_name"][0].data
        if "optional_check_idents" in request.inputs:
            optional_check_idents = request.inputs["optional_check_idents"][0].data
            optional_check_idents = optional_check_idents.split(",")
        else:
            optional_check_idents = []

        # Call dispatch.
        def update_wps_result(suite_result):
            response.outputs["result"].data = json.dumps(suite_result)
        dispatch(str(self.uuid),
                 filepath,
                 product_type_name,
                 optional_check_idents,
                 update_result_func=update_wps_result)
        return response
