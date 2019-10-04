#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Metadata are in accord with INSPIRE specification."
IS_SYSTEM = False


def locate_xml_file(layer_filepath):
    # The INSPIRE XML file can be LAYER.xml or LAYER.tif.xml or LAYER_metadata.xml.
    # The file can also be located in a "metadata" subdirectory.
    for xml_filepath in [layer_filepath.parent.joinpath(layer_filepath.name + ".xml"),
                         layer_filepath.parent.joinpath(layer_filepath.stem + ".xml"),
                         layer_filepath.parent.joinpath(layer_filepath.stem + "_metadata.xml"),
                         layer_filepath.parent.joinpath("metadata", layer_filepath.name + ".xml"),
                         layer_filepath.parent.joinpath("metadata", layer_filepath.stem + ".xml"),
                         layer_filepath.parent.joinpath("metadata", layer_filepath.stem + "_metadata.xml")]:
        if xml_filepath.exists():
            return xml_filepath
    return None


def run_check(params, status):
    from qc_tool.vector.helper import do_inspire_check
    from qc_tool.raster.helper import do_raster_layers

    for layer_def in do_raster_layers(params):
        # Verify if there is any xml INSPIRE metadata file to check.
        xml_filepath = locate_xml_file(layer_def["src_filepath"])
        if xml_filepath is None:
            status.failed("Metadata file for {:s} has not been found.".format(layer_def["src_filepath"].name))
            return

        # Validate the xml file using INSPIRE validator service
        export_prefix = "s{:02d}_{:s}_inspire".format(params["step_nr"], layer_def["src_filepath"].stem)
        do_inspire_check(xml_filepath, export_prefix, params["output_dir"], status)
