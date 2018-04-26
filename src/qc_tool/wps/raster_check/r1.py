#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
File format check.
"""

import os
import gdal

from registry import register_check_function

@register_check_function(__name__, "File format is allowed.")
def run_check(filepath, params):
    """
    File format check.
    :param filepath: pathname to data source
    :param params: configuration
    :return: status + message
    """

    print("run_check.filepath={:s}".format(repr(filepath)))
    print("run_check.params={:s}".format(repr(params)))

    # enable gdal to use exceptions
    gdal.UseExceptions()

    # file extension check
    ds_extension = os.path.splitext(filepath)[1]
    if ds_extension not in params["formats"]:
        return {"status": "failed",
                "message": "forbidden file extension {:s}".format(ds_extension)}

    # try to open file with ogr drivers
    if ds_extension in params["drivers"]:
        try:
            ds_open = gdal.Open(filepath)
            if ds_open is None:
                return {"status": "failed",
                        "message": "file can not be opened"}
        except:
            return {"status": "failed",
                    "message": "file can not be opened"}

        # check file format
        drivername = ds_open.GetDriver().ShortName
        if drivername == params["drivers"][ds_extension]:
            return {"status": "ok",
                    "message": "the file format check was successful"}
        else:
            return {"status": "failed",
                    "message": "file format is invalid"}
    else:
        return {"status": "failed",
                "message": "forbidden file extension {:s}".format(ds_extension)}
