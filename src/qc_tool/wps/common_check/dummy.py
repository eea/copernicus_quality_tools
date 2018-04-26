#! /usr/bin/env python


import re

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__, "Dummy check for testing purposes.")
def run(filepath, params):
    return {"status": "ok",
            "message": "Dummy check has passed.",
            "params": repr(params)}
