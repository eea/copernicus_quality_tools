#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Delivery content uses specific file format."
IS_SYSTEM = False


def run_check(params, status):
    import osgeo.ogr as ogr

    from qc_tool.vector.helper import do_layers

    # enable ogr to use exceptions
    ogr.UseExceptions()

    filepaths = set(layer_def["src_filepath"] for layer_def in do_layers(params))
    for filepath in filepaths:
        ds_extension = filepath.suffix
        if (ds_extension not in params["formats"]
            or ds_extension not in params["drivers"]):
            status.aborted("The source file has forbidden extension: {:s}".format(ds_extension))
        else:
            ds_open = None
            try:
                ds_open = ogr.Open(str(filepath))
            except:
                pass
            if ds_open is None:
                status.aborted("The source file can not be opened.")
            else:
                drivername = ds_open.GetDriver().GetName()
                if drivername != params["drivers"][ds_extension]:
                    status.aborted("The file format is invalid.")
