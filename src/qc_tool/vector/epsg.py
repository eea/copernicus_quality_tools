#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Layers use specific EPSG codes."
IS_SYSTEM = False


def run_check(params, status):
    import osgeo.ogr as ogr
    import osgeo.osr as osr

    from qc_tool.vector.helper import do_layers

    # Check if the current delivery is excluded from vector checks
    if "skip_vector_checks" in params:
        if params["skip_vector_checks"]:
            status.info("The delivery has been excluded from vector.epsg check because the vector data source does not contain a single object of interest.")
            return

    for layer_def in do_layers(params):
        ds = ogr.Open(str(layer_def["src_filepath"]))
        layer = ds.GetLayerByName(layer_def["src_layer_name"])
        srs = layer.GetSpatialRef()
        if srs is None:
            status.aborted("Layer {:s} has missing spatial reference system.".format(layer_def["src_layer_name"]))
        else:
            # Get epsg code from authority clause.
            srs.AutoIdentifyEPSG()
            authority_name = srs.GetAuthorityName(None)
            authority_code = srs.GetAuthorityCode(None)
            if authority_name == "EPSG":
                # Compare epsg code using the root-level epsg authority in the srs WKT of the layer.
                try:
                    authority_code = int(authority_code)
                except ValueError:
                    status.aborted("Layer {:s} has non integer epsg code {:s}".format(layer_def["src_layer_name"], authority_code))
                else:
                    if authority_code != params["epsg"]:
                        status.aborted("Layer {:s} has illegal epsg code {:d}.".format(layer_def["src_layer_name"], authority_code))
                    else:
                        status.add_params({"detected_epsg": authority_code})
            elif params.get("auto_identify_epsg", False):
                # Parameter auto_identify_epsg can be used for less-strict checking of .prj files.
                # There is a built-in function in GDAL 2.3 with matching logic.
                is_detected = False
                expected_srs = osr.SpatialReference()
                expected_srs.ImportFromEPSG(params["epsg"])
                if srs.IsSame(expected_srs):
                    # The auto-detected epsg is made available for other checks.
                    status.add_params({"detected_epsg": params["epsg"]})
                else:
                    status.aborted("Layer {:s} does not have an epsg code and the epsg code can not be detected, srs: {:s}."
                                   .format(layer_def["src_layer_name"], srs.ExportToWkt()))
            else:
                # the setting is strict and no epsg code has been found in the srs of the layer.
                status.aborted("Layer {:s} has epsg code missing, srs: {:s}."
                               .format(layer_def["src_layer_name"], srs.ExportToWkt()))
