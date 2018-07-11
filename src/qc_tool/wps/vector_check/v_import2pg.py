#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from subprocess import run

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    dsn, schema =  params["connection_manager"].get_dsn_schema()

    for layer_name in params["layer_names"]:
        pc = run(["ogr2ogr",
                   "-overwrite",
                   "-skipfailures",
                   "-f", "PostgreSQL",
                   "-lco", "SCHEMA={:s}".format(schema),
                   "PG:{:s}".format(dsn),
                   str(params["filepath"]),
                   layer_name])
        if pc.returncode != 0:
            status.aborted()
            status.add_message("Importing of {:s} layer into PostGIS db failed.".format(layer_name))
