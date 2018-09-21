#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import re
from osgeo import ogr

from qc_tool.wps.registry import register_check_function


def check_name(name, template):
    regex = re.compile(template)
    return bool(regex.match(name))


@register_check_function(__name__)
def run_check(params, status):
    """
    Find layers in a file geodatabase (.gdb) or in a directory with shapefiles.
    :param params:
    :param status:
    :return:
    """
    reference_year = None
    all_directories = [path for path in params["unzip_dir"].glob("**") if path.is_dir()]
    layer_regex = re.compile(params["layer_regex"], re.IGNORECASE)

    # Find gdb folder. There must be zero or exactly one .gdb folder in the unzipped directory tree.
    gdb_filepaths = [path for path in all_directories if path.suffix.lower() == ".gdb"]
    if len(gdb_filepaths) > 1:
        status.aborted()
        gdb_filenames = [path.name for path in gdb_filepaths]
        status.add_message("There cannot be more than one geodatabase in a delivery. "
                           "{:d} geodatabases found ({:s}).".format(len(gdb_filepaths), ", ".join(gdb_filenames)))

    if len(gdb_filepaths) == 1:
        # option 1: GEODATABASE
        gdb_filepath = gdb_filepaths[0]
        ds = ogr.Open(str(gdb_filepath))
        if ds is None:
            status.aborted()
            status.add_message("Geodatabase {:s} could not be opened.".format(gdb_filepath.name))

        # Check the opened .gdb for matching layers.
        matched_layer_names = []
        for layer_index in range(ds.GetLayerCount()):
            layer = ds.GetLayerByIndex(layer_index)
            mobj = re.match(layer_regex, layer.GetName())
            if mobj is not None:
                layer_reference_year = mobj.group("reference_year")[-4:]
                if reference_year is None or reference_year < layer_reference_year:
                    reference_year = layer_reference_year
                matched_layer_names.append(layer.GetName())

        if len(matched_layer_names) == 0:
            status.aborted()
            status.add_message("Geodatabase {:s} does not have any layers matching expected naming convention pattern "
                               "{:s}.".format(gdb_filepath.name, params["layer_regex"]))
            return

        status.set_status_property("reference_year", reference_year)

        if len(matched_layer_names) != params["layer_count"]:
            status.aborted()
            status.add_message("Geodatabase {:s} contains {:d} layers matching the naming convention. "
                               "Expected number of layers is {:d}. Layers found in the geodatabase are: "
                               "({:s}).".format(gdb_filepath.name, len(matched_layer_names),
                                              params["layer_count"], ", ".join(matched_layer_names)))
            return

        # Geodatabase layers are OK --> add parameters to status and exit
        layer_sources = [(layer_name.lower(), gdb_filepath) for layer_name in matched_layer_names]
        status.add_params({"layer_sources": layer_sources})
        if params.get("is_border_source", False):
            status.add_params({"border_source_layer": matched_layer_names[0]})
        return

    else:
        # option 2: SHAPEFILES
        all_filepaths = [path for path in params["unzip_dir"].glob("**/*") if path.is_file()]
        shp_filepaths = [path for path in all_filepaths if path.suffix.lower() == ".shp"]
        matched_shp_filepaths = []
        for path in shp_filepaths:
            mobj = layer_regex.match(path.stem)
            if mobj is not None:
                layer_reference_year = mobj.group("reference_year")
                layer_reference_year = layer_reference_year[-4:]
                if reference_year is None or reference_year < layer_reference_year:
                    reference_year = layer_reference_year
                matched_shp_filepaths.append(path)

        if len(matched_shp_filepaths) == 0:
            status.aborted()
            status.add_message("Delivery does not contain any geodatabase or shapefile layers matching the naming "
                               "convention. Expected number of layers is {:d}.".format(params["layer_count"]))

        status.set_status_property("reference_year", reference_year)

        if len(matched_shp_filepaths) != params["layer_count"]:
            status.aborted()
            status.add_message("Delivery contains {:d} shapefile layers matching the naming convention. "
                               "Expected number of layers is {:d}. Layers found in the delivery are: "
                               "({:s})".format(len(matched_shp_filepaths),
                                               params["layer_count"],
                                               ",".join(matched_shp_filepaths)))
            return

        # Get layers from shapefile names. Layer names are always considered lower-case.
        layer_sources = [(filepath.stem.lower(), filepath) for filepath in matched_shp_filepaths]
        status.add_params({"layer_sources": layer_sources})
        if params.get("is_border_source", False):
            status.add_params({"border_source_layer": layer_sources[0][0].lower()})
