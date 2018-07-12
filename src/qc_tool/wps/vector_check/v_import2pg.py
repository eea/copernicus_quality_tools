#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from subprocess import run

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    dsn, schema =  params["connection_manager"].get_dsn_schema()

    db_layer_names = []
    for layer_name, layer_filepath in params["layer_sources"]:
        pc = run(["ogr2ogr",
                   "-overwrite",
                   "-skipfailures",
                   "-f", "PostgreSQL",
                   "-lco", "SCHEMA={:s}".format(schema),
                   "PG:{:s}".format(dsn),
                   str(layer_filepath),
                   layer_name])
        if pc.returncode == 0:
            db_layer_names.append(layer_name)
        else:
            status.aborted()
            status.add_message("Importing of {:s} layer into PostGIS db failed.".format(layer_name))
    status.add_params({"db_layer_names": db_layer_names})
