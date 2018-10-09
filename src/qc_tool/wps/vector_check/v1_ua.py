#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import re
from osgeo import ogr

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    """
    Find layers in a file geodatabase (.gdb) or in a directory with shapefiles.
    """
    reference_year = None
    layer_name_regex = re.compile(params["layer_name_regex"], re.IGNORECASE)

    # Find gdb folder. There must be zero or exactly one .gdb folder in the unzipped directory tree.
    gdb_dirs = [path for path in params["unzip_dir"].glob("**") if path.is_dir() and path.suffix.lower() == ".gdb"]
    if len(gdb_dirs) > 1:
        status.aborted()
        gdb_names = [gdb_dir.name for gdb_dir in gdb_dirs]
        status.add_message("There cannot be more than one geodatabase in a delivery. "
                           "{:d} geodatabases found ({:s}).".format(len(gdb_dirs), ", ".join(gdb_names)))

    if len(gdb_dirs) == 1:
        # option 1: GEODATABASE
        gdb_dir = gdb_dirs[0]
        ds = ogr.Open(str(gdb_dir))
        if ds is None:
            status.aborted()
            status.add_message("Geodatabase {:s} could not be opened.".format(gdb_dir.name))

        # Check the opened .gdb for matching layers.
        matched_layer_names = []
        for layer_index in range(ds.GetLayerCount()):
            layer = ds.GetLayerByIndex(layer_index)
            layer_name = layer.GetName()
            mobj = layer_name_regex.search(layer_name)
            if mobj is not None:
                layer_reference_year = mobj.group("reference_year")
                if reference_year is None or reference_year < layer_reference_year:
                    reference_year = layer_reference_year
                matched_layer_names.append(layer_name)

        if len(matched_layer_names) == 0:
            status.aborted()
            status.add_message("Geodatabase {:s} does not have any layers matching expected naming convention pattern "
                               "{:s}.".format(gdb_dir.name, params["layer_name_regex"]))
            return

        status.set_status_property("reference_year", reference_year)

        if len(matched_layer_names) != params["layer_count"]:
            status.aborted()
            status.add_message("Geodatabase {:s} contains {:d} layers matching the naming convention. "
                               "Expected number of layers is {:d}. Layers found in the geodatabase are: "
                               "({:s}).".format(gdb_dir.name, len(matched_layer_names),
                                              params["layer_count"], ", ".join(matched_layer_names)))
            return

        layer_aliases = {"layer_{:d}".format(i): {"src_filepath": gdb_dir,
                                                  "src_layer_name": layer_name}
                         for i, layer_name in enumerate(matched_layer_names)}
        status.add_params({"layer_aliases": layer_aliases})
        if params.get("is_border_source", False):
            status.add_params({"border_source_layer": matched_layer_names[0]})

    else:
        # option 2: SHAPEFILES
        shp_filepaths = [path for path in params["unzip_dir"].glob("**/*") if path.is_file() and path.suffix.lower() == ".shp"]
        matched_shp_filepaths = []
        for shp_filepath in shp_filepaths:
            mobj = layer_name_regex.search(shp_filepath.stem)
            if mobj is not None:
                layer_reference_year = mobj.group("reference_year")
                if reference_year is None or reference_year < layer_reference_year:
                    reference_year = layer_reference_year
                matched_shp_filepaths.append(shp_filepath)

        if len(matched_shp_filepaths) == 0:
            status.aborted()
            status.add_message("Delivery does not contain any geodatabase or shapefile layers matching the naming "
                               "convention. Expected number of layers is {:d}.".format(params["layer_count"]))
            return

        status.set_status_property("reference_year", reference_year)

        if len(matched_shp_filepaths) != params["layer_count"]:
            status.aborted()
            layer_names = [shp_filepath.stem for shp_filepath in matched_shp_filepaths]
            status.add_message("Delivery contains {:d} shapefile layers matching the naming convention. "
                               "Expected number of layers is {:d}. Layers found in the delivery are: "
                               "({:s})".format(len(matched_shp_filepaths),
                                               params["layer_count"],
                                               ", ".join(layer_names)))
            return

        layer_aliases = {"layer_{:d}".format(i): {"src_filepath": shp_filepath,
                                                  "src_layer_name": shp_filepath.stem}
                         for i, shp_filepath in enumerate(matched_shp_filepaths)}
        status.add_params({"layer_aliases": layer_aliases})
        if params.get("is_border_source", False):
            status.add_params({"border_source_layer": matched_shp_filepaths[0].stem})
