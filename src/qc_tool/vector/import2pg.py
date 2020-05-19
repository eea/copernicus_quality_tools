#!/usr/bin/env python3
# -*- coding: utf-8 -*-


from subprocess import run


DESCRIPTION = "The layers can be imported into PostGIS database."
IS_SYSTEM = True


def run_check(params, status):
    from osgeo import ogr
    from osgeo.gdalconst import OF_READONLY

    from qc_tool.vector.helper import do_layers

    dsn, schema =  params["connection_manager"].get_dsn_schema()

    # Import all layers found in layer_defs.
    for layer_def in params["layer_defs"].values():
        src_layer_name = layer_def["src_layer_name"]
        pg_layer_name = layer_def["layer_alias"]

        if "detected_epsg" in params:
            pc = run(["ogr2ogr",
                      "-overwrite",
                      "-f", "PostgreSQL",
                      "-lco", "GEOMETRY_NAME=geom",
                      "-lco", "SCHEMA={:s}".format(schema),
                      "-lco", "PRECISION=NO",
                      "-nlt", "MULTIPOLYGON",
                      "-nln", pg_layer_name,
                      "-a_srs", "EPSG:{:d}".format(params["detected_epsg"]),
                      "PG:{:s}".format(dsn),
                      str(layer_def["src_filepath"]),
                      src_layer_name])
        else:
            pc = run(["ogr2ogr",
                      "-overwrite",
                      "-f", "PostgreSQL",
                      "-lco", "GEOMETRY_NAME=geom",
                      "-lco", "SCHEMA={:s}".format(schema),
                      "-lco", "PRECISION=NO",
                      "-nlt", "MULTIPOLYGON",
                      "-nln", pg_layer_name,
                      "PG:{:s}".format(dsn),
                      str(layer_def["src_filepath"]),
                      src_layer_name])
        if pc.returncode != 0:
            status.aborted("Failed to import layer {:s} into PostGIS.".format(src_layer_name))
        else:
            # ogr2ogr not always returns non-zero exit code in case of error.
            # Therefore we try some checking whether the layer has been imported correctly.

            ## Open datasource from filesystem.
            src_datasource = ogr.Open(str(layer_def["src_filepath"]), OF_READONLY)
            src_layer = src_datasource.GetLayerByName(src_layer_name)

            ## Open datasource from postgis.
            conn_string = "PG:{:s} active_schema={:s}".format(dsn, schema)
            dst_datasource = ogr.Open(conn_string, OF_READONLY)
            # NOTE: GetLayerByName() works case insensitive in this case.
            dst_layer = dst_datasource.GetLayerByName(pg_layer_name)
            if dst_layer is None:
                status.aborted("Just imported layer {:s} can not be found in postgis.".format(src_layer_name))
            else:
                ## Set pg info back to layer_defs.
                ##
                ## FIXME: such construct is not really clear while it exploits mutable dictionaries
                ## and bypasses currently standard use of status.add_params().
                layer_def["pg_layer_name"] = pg_layer_name
                layer_def["pg_fid_name"] = dst_layer.GetFIDColumn().lower()
                if layer_def["pg_fid_name"] == "objectid":
                    layer_def["fid_display_name"] = "objectid"
                else:
                    layer_def["fid_display_name"] = "row number"

                ## Ensure all features has been imported.
                src_count = src_layer.GetFeatureCount()
                dst_count = dst_layer.GetFeatureCount()
                if src_count != dst_count:
                    status.aborted("Imported layer {:s} has only {:d} out of {:d} features loaded."
                                   .format(src_layer_name, dst_count, src_count))
