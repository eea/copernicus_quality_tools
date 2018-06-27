#! /usr/bin/env python


import re

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run(filepath, params):
    return {"status": "ok",
            "message": "Dummy check has passed.",
            "params": {"dummy_job_param1": "dummy_job_param1",
                       "dummy_job_param2": "dummy_job_param2"}}
