#! /usr/bin/env python
# -*- coding: utf-8 -*-


import re


DESCRIPTION = "Naming is in accord with specification."
IS_SYSTEM = False


def run_check(params, status):
    from qc_tool.vector.helper import LayerDefsBuilder

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

    # Extract AOI code and compare it to pre-defined list.
    if "aoi_codes" in params and len(params["aoi_codes"]) > 0:
        layer_aoi_codes = []
        for layer_alias, layer_def in builder.layer_defs.items():
            layer_name = layer_def["src_layer_name"]
            layer_regex = params["layer_names"][layer_alias]
            mobj = re.match(layer_regex, layer_name.lower())
            if mobj is None:
                status.aborted("Layer {:s} has illegal name: {:s}.".format(layer_alias, layer_name))
                continue
            try:
                aoi_code = mobj.group("aoi_code")
            except IndexError:
                status.aborted("Layer {:s} does not contain AOI code.".format(layer_name))
                continue
            layer_aoi_codes.append(aoi_code)
            if aoi_code not in params["aoi_codes"]:
                status.aborted("Layer {:s} has illegal AOI code {:s}.".format(layer_name, aoi_code))
                continue

        # Check that AOI code could be detected.
        if len(set(layer_aoi_codes)) == 0:
            status.aborted("AOI code could not be detected from any layer name.")
            return

        # If there are multiple layers, check that all layers have the same AOI code.
        if len(set(layer_aoi_codes)) > 1:
            status.aborted("Layers do not have the same AOI code. Detected AOI codes: {:s}"
                           .format(",".join(list(layer_aoi_codes))))

        # Set aoi_code as a global parameter.
        status.add_params({"aoi_code": layer_aoi_codes[0]})

    # Extract reference year (might not be needed).
    if "extract_reference_year" in params and params["extract_reference_year"] == True:
        for layer_alias, layer_def in builder.layer_defs.items():
            layer_def = builder.layer_defs[layer_alias]
            layer_name = layer_def["src_layer_name"]
            layer_regex = params["layer_names"][layer_alias]
            mobj = re.match(layer_regex, layer_name.lower())
            if mobj is not None:
                try:
                    reference_year = mobj.group("reference_year")
                    status.set_status_property("reference_year", reference_year)
                except IndexError:
                    status.aborted("Layer {:s} does not contain reference year".format(layer_name))

    # Checking existence of required supplementary files for each GeoTiff (i.e. .tfw)
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
