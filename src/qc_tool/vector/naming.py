#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Naming is in accord with specification."
IS_SYSTEM = False


def run_check(params, status):

    from qc_tool.vector.helper import LayerDefsBuilder
    from qc_tool.vector.helper import check_gdb_filename
    from qc_tool.vector.helper import extract_aoi_code
    from qc_tool.vector.helper import find_gdb_layers
    from qc_tool.vector.helper import find_shp_layers


    # Fix reference year.
    if "reference_year" in params:
        status.set_status_property("reference_year", params["reference_year"])

    # Find shp layers.
    shp_layer_infos = []
    if ".shp" in params["formats"]:
        shp_layer_infos = find_shp_layers(params["unzip_dir"], status)

    # Find gdb layers.
    gdb_layer_infos = []
    if ".gdb" in params["formats"]:
        gdb_layer_infos = find_gdb_layers(params["unzip_dir"], status)

    # Check if delivery contains any vector layers.
    if len(shp_layer_infos) + len(gdb_layer_infos) == 0:
        status.aborted("No {:s} vector layers were found in the delivery.".format(" or ".join(params["formats"])))
        return

    # Check number of geodatabases.
    gdb_filepaths = set([layer_info["src_filepath"] for layer_info in gdb_layer_infos])
    if "num_geodatabases" in params:
        if len(gdb_filepaths) != params["num_geodatabases"]:
            status.aborted("Expected number of geodatabases in the delivery is {:d} but"
                           "{:d} geodatabases have been found: "
                           .format(params["num_geodatabases"],
                                   len(gdb_filepaths),
                                   ", ".join([gdb_dir.name for gdb_dir in gdb_filepaths])))
            return

    # Read all shapefile layer infos into builder.
    builder = LayerDefsBuilder(status)
    if ".shp" in params["formats"]:
        for shp_layer_info in shp_layer_infos:
            builder.add_layer_info(shp_layer_info["src_filepath"], shp_layer_info["src_layer_name"])

    # Read all geodatabase layer infos into builder.
    if ".gdb" in params["formats"]:
        for gdb_layer_info in gdb_layer_infos:
            builder.add_layer_info(gdb_layer_info["src_filepath"], gdb_layer_info["src_layer_name"])

    # If no layer_names parameter is specified then pass on all vector layers to other checks.
    if "layer_names" not in params:
        builder.extract_all_layers()
        status.add_params({"layer_defs": builder.layer_defs})
        return

    # Build layer defs for all layers.
    for layer_alias, layer_regex in params["layer_names"].items():
        builder.extract_layer_def(layer_regex, layer_alias)

    # Check excessive layers.
    excessive_layers_allowed = params.get("excessive_layers_allowed", False)
    if not excessive_layers_allowed:
        builder.check_excessive_layers()

    # Extract AOI code and compare it to pre-defined list.
    aoi_code = None
    if "aoi_codes" in params and len(params["aoi_codes"]) > 0:
        aoi_code = extract_aoi_code(builder.layer_defs, params["layer_names"], params["aoi_codes"], status)
        status.add_params({"aoi_code": aoi_code})

    # Check geodatabase name. If set, the aoi_code in the geodatabase name should match aoi_code from the layers.
    if "gdb_filename_regex" in params:
        for gdb_filepath in gdb_filepaths:
            check_gdb_filename(gdb_filepath, params["gdb_filename_regex"], aoi_code, status)

    # Find boundary layer.
    if "boundary_source" in params:

        # If boundary expression contains '{aoi_code}' then try to inject aoi_code into boundary file path.
        boundary_source_name = params["boundary_source"]
        if "{aoi_code}" in params["boundary_source"] and aoi_code is not None:
            boundary_source_name = boundary_source_name.format(**{"aoi_code": aoi_code})

        boundary_filepath = params["boundary_dir"].joinpath("vector", boundary_source_name)
        if boundary_filepath.is_file():
            builder.layer_defs["boundary"] = {"src_filepath": boundary_filepath,
                                              "src_layer_name": boundary_filepath.stem}
        else:
            status.info("No boundary has been found at {:s}."
                        .format(boundary_source_name))

    status.add_params({"layer_defs": builder.layer_defs})
