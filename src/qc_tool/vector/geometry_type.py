#!/usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Layer has the required geometry type."
IS_SYSTEM = False

# Mapping from user-friendly names to OGR wkb type constants (populated at runtime).
GEOMETRY_TYPE_ALIASES = {
    "point":           "wkbPoint",
    "multipoint":      "wkbMultiPoint",
    "line":            "wkbLineString",
    "linestring":      "wkbLineString",
    "multiline":       "wkbMultiLineString",
    "multilinestring": "wkbMultiLineString",
    "polygon":         "wkbPolygon",
    "multipolygon":    "wkbMultiPolygon",
}


def run_check(params, status):
    import osgeo.ogr as ogr

    from qc_tool.vector.helper import do_layers

    raw_type = params["geometry_type"]
    wkb_name = GEOMETRY_TYPE_ALIASES.get(raw_type.lower())
    if wkb_name is None:
        status.aborted("Unknown geometry_type parameter value: '{:s}'.".format(raw_type))
        return
    expected_wkb = getattr(ogr, wkb_name)

    for layer_def in do_layers(params):
        ds = ogr.Open(str(layer_def["src_filepath"]))
        layer = ds.GetLayerByName(layer_def["src_layer_name"])

        # Flatten to 2D so that 3D/2.5D variants (e.g. wkbPolygon25D) compare equal.
        actual_wkb = ogr.GT_Flatten(layer.GetGeomType())
        actual_name = ogr.GeometryTypeToName(actual_wkb)

        if actual_wkb != expected_wkb:
            status.aborted(
                "Layer {:s} has geometry type '{:s}' but '{:s}' was expected.".format(
                    layer_def["src_layer_name"], actual_name, ogr.GeometryTypeToName(expected_wkb)
                )
            )
