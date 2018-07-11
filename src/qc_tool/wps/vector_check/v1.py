#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from osgeo import ogr

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    # enable ogr to use exceptions
    ogr.UseExceptions()

    # file extension check
    ds_extension = params["filepath"].suffix
    if ds_extension not in params["formats"]:
        status.aborted()
        status.add_message("The source file has forbidden extension: {:s}".format(ds_extension))
        return

    # try to open file with ogr drivers
    if ds_extension in params["drivers"]:
        try:
            ds_open = ogr.Open(str(params["filepath"]))
            if ds_open is None:
                status.aborted()
                status.add_message("The source file can not be opened.")
                return
        except:
            status.aborted()
            status.add_message("The source file can not be opened.")
            return

        # check file format
        drivername = ds_open.GetDriver().GetName()
        if drivername == params["drivers"][ds_extension]:
            return
        else:
            status.aborted()
            status.add_message("The file format is invalid.")
            return
    else:
        status.aborted()
        status.add_message("The source file has forbidden extension: {:s}".format(ds_extension))
        return
