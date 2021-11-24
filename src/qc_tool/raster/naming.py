#! /usr/bin/env python
# -*- coding: utf-8 -*-


import re


DESCRIPTION = "Naming is in accord with specification."
IS_SYSTEM = False


def run_check(params, status):
    import osgeo.gdal as gdal
    from qc_tool.vector.helper import LayerDefsBuilder
    from qc_tool.vector.helper import extract_aoi_code
    from qc_tool.vector.helper import extract_epsg_code

    # Fix reference year.
    if "reference_year" in params:
        status.set_status_property("reference_year", params["reference_year"])

    # Find tif files.
    tif_filepaths = [path for path in list(params["unzip_dir"].glob("**/*"))
                     if path.name.lower().endswith(".tif") and path.is_file()]

    if len(tif_filepaths) == 0:
        status.aborted("No .tif files were found in the delivery.")
        return

    # Read all layer infos into builder.
    builder = LayerDefsBuilder(status)
    for filepath in tif_filepaths:
        builder.add_layer_info(filepath, filepath.name)

    # Build layer defs for all .tif files in the delivery.
    for layer_alias, layer_regex in params["layer_names"].items():
        builder.extract_layer_def(layer_regex, layer_alias)

    # Check excessive layers.
    builder.check_excessive_layers()
    status.add_params({"raster_layer_defs": builder.layer_defs})

    # Check AOI codes.
    if "aoi_codes" in params and len(params["aoi_codes"]) > 0:
        if params["aoi_codes"][0] == "*":
            preserve_aoicode_case = True
            compare_aoi_codes = False
        else:
            preserve_aoicode_case = False
            compare_aoi_codes = True
        aoi_code = extract_aoi_code(builder.layer_defs, params["layer_names"], params["aoi_codes"], status,
                                    preserve_aoicode_case=preserve_aoicode_case, compare_aoi_codes=compare_aoi_codes)
        status.add_params({"aoi_code": aoi_code})

    # Check EPSG codes.
    if "epsg_codes" in params and len(params["epsg_codes"]) > 0:
        compare_epsg_codes = True
        name_epsg = extract_epsg_code(builder.layer_defs, params["layer_names"], params["epsg_codes"], status,
                                    compare_epsg_codes=compare_epsg_codes)
        status.add_params({"name_epsg": name_epsg})

    # Check raster file format.
    for layer_alias, layer_def in builder.layer_defs.items():
        ds = gdal.Open(str(layer_def["src_filepath"]))
        if ds is None:
            status.aborted("The raster {:s} cannot be opened."
                           .format(layer_def["src_filepath"].name))
            continue
        if ds.RasterCount != 1:
            # Check number of bands. Only one band is allowed.
            status.aborted("The raster {:s} has {:d} bands. The expected number of bands is one."
                           .format(layer_def["src_filepath"].name, ds.RasterCount))

    # Check existence of required supplementary files for each GeoTiff (i.e. .tfw)
    if "extensions" in params:
        for layer_alias, layer_def in builder.layer_defs.items():
            for ext in params["extensions"]:
                # The extension can be specified as .clr or .tif.clr (.clr|.tif.clr)
                if "|" in ext:
                    ext_options = ext.split("|")
                else:
                    ext_options = [ext]

                expected_files = [layer_def["src_filepath"].with_suffix(ext_opt).name for ext_opt in ext_options]

                found_files = []
                if len(expected_files) == 1:
                    expected_files_msg = expected_files[0]
                else:
                    expected_files_msg = " or ".join(expected_files)

                for ext2 in ext_options:
                    other_filepath = layer_def["src_filepath"].with_suffix(ext2)
                    if other_filepath.exists():
                        found_files.append(other_filepath.name)

                if len(found_files) == 0:
                    status.aborted("Layer {:s} has missing supplementary files: '{:s}'."
                                   .format(layer_def["src_layer_name"], expected_files_msg))
