#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Metadata are in accord with INSPIRE specification."
IS_SYSTEM = False


def locate_xml_file(metadata_folder_path, layer_filepath):
    # The INSPIRE XML file can be LAYER.xml or LAYER_metadata.xml.
    for xml_filepath in [metadata_folder_path.joinpath(layer_filepath.stem + ".xml"),
                         metadata_folder_path.joinpath(layer_filepath.stem + "_metadata.xml")]:
        if xml_filepath.exists():
            return xml_filepath
    return None


def run_check(params, status):
    from qc_tool.vector.helper import do_inspire_check
    from qc_tool.raster.helper import do_raster_layers

    for layer_def in do_raster_layers(params):

        # Verify that there is a Metadata subfolder.
        metadata_dir = layer_def["src_filepath"].parent.joinpath("Metadata")
        if not metadata_dir.is_dir():
            status.info("The delivery does not contain the expected 'Metadata' folder.")
            return

        # The .xml file must be placed inside a Metadata subdirectory.
        xml_filepath = locate_xml_file(metadata_dir, layer_def["src_filepath"])
        if xml_filepath is None:
            status.info("The delivery does not contain the expected metadata file 'Metadata/{:s}.xml'".format(
                layer_def["src_filepath"].stem))
            return

        # Validate the xml file using INSPIRE validator service
        export_prefix = "s{:02d}_{:s}_inspire".format(params["step_nr"], layer_def["src_filepath"].stem)
        do_inspire_check(xml_filepath, export_prefix, params["output_dir"], status)
