#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
File format check.
"""


from osgeo import ogr

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params):
    """
    File format check.
    :param params: configuration
    :return: status + message
    """

    # enable ogr to use exceptions
    ogr.UseExceptions()

    # file extension check
    ds_extension = params["filepath"].suffix
    if ds_extension not in params["formats"]:
        return {"status": "aborted",
                "messages": ["The source file has forbidden extension: {:s}".format(ds_extension)]}

    # try to open file with ogr drivers
    if ds_extension in params["drivers"]:
        try:
            ds_open = ogr.Open(str(params["filepath"]))
            if ds_open is None:
                return {"status": "aborted",
                        "messages": ["The source file can not be opened."]}
        except:
            return {"status": "aborted",
                    "messages": ["The source file can not be opened."]}

        # check file format
        drivername = ds_open.GetDriver().GetName()
        if drivername == params["drivers"][ds_extension]:
            return {"status": "ok"}
        else:
            return {"status": "aborted",
                    "messages": ["The file format is invalid."]}
    else:
        return {"status": "aborted",
                "messages": ["The source file has forbidden extension: {:s}".format(ds_extension)]}
