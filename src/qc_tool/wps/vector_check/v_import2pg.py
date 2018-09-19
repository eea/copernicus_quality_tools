#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from subprocess import run

from osgeo import ogr
from osgeo.gdalconst import OF_READONLY

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    dsn, schema =  params["connection_manager"].get_dsn_schema()

    db_layers = []
    for layer_name, layer_filepath in params["layer_sources"]:
        pc = run(["ogr2ogr",
                   "-overwrite",
                   "-f", "PostgreSQL",
                   "-lco", "SCHEMA={:s}".format(schema),
                   "-lco", "PRECISION=NO",
                   "-nlt", "MULTIPOLYGON",
                   "PG:{:s}".format(dsn),
                   str(layer_filepath),
                   layer_name])
        if pc.returncode == 0:
            # ogr2ogr not always returns non-zero exit code in case of error.
            # Therefore we try some checking whether the layer has been imported correctly.

            ## Open datasource from filesystem.
            src_datasource = ogr.Open(str(layer_filepath), OF_READONLY)
            src_layer = src_datasource.GetLayerByName(layer_name)

            ## Open datasource from postgis.
            conn_string = "PG:{:s} active_schema={:s}".format(dsn, schema)
            dst_datasource = ogr.Open(conn_string, OF_READONLY)
            # NOTE: GetLayerByName() works case insensitive in this case.
            dst_layer = dst_datasource.GetLayerByName(layer_name)
            if dst_layer is None:
                status.aborted()
                status.add_message("Just imported layer {:s} can not be found in postgis.".format(layer_name))

            else:
                ## Ensure all features has been imported.
                src_count = src_layer.GetFeatureCount()
                dst_count = dst_layer.GetFeatureCount()
                if src_count != dst_count:
                    status.aborted()
                    status.add_message("Imported layer {:s} has {:d} out of {:d} features loaded.".format(layer_name, dst_count, src_count))
                else:
                    fid_column_name = dst_layer.GetFIDColumn()
                    db_layers.append((layer_name, fid_column_name))
        else:
            status.aborted()
            status.add_message("Importing of layer {:s} into PostGIS db failed.".format(layer_name))

    # Get fid column name.
    # Check that all layers have fid column of the same name.
    # Such name will be used as the name of the primary key column in all the layers.
    fid_column_name = None
    fid_column_names = set([fid_column_name for layer_name, fid_column_name in db_layers])
    if len(fid_column_names) == 1:
        fid_column_name = fid_column_names.pop()
    elif len(fid_column_names) > 1:
        status.aborted()
        layer_infos = ['"{:s}"."{:s}"'.format(layer_name, fid_column_name)
                       for layer_name, fid_column_name in db_layers]
        status.add_message("The layers have distinct fid column names: {:s}.".format(", ".join(layer_infos)))

    # Set job params.
    db_layer_names = [layer_name for layer_name, fid_column_name in db_layers]
    status.add_params({"fid_column_name": fid_column_name,
                       "db_layer_names": db_layer_names})
