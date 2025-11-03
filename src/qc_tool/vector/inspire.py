#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Metadata are in accord with INSPIRE specification."
IS_SYSTEM = False

METADATA_DIRNAME = "metadata"


def locate_xml_file(metadata_folder_path, layer_filepath):
    # The INSPIRE XML file can be LAYER.xml or LAYER_metadata.xml.
    for xml_filepath in [metadata_folder_path.joinpath(layer_filepath.stem + ".xml"),
                         metadata_folder_path.joinpath(layer_filepath.stem + "_metadata.xml")]:
        if xml_filepath.exists():
            return xml_filepath
    return None


def run_check(params, status):
    from qc_tool.vector.helper import do_inspire_check
    from qc_tool.vector.helper import do_layers

    # Check if the current delivery is excluded from vector checks
    if "skip_vector_checks" in params:
        if params["skip_vector_checks"]:
            status.info("The delivery has been excluded from vector.inspire check because the vector data source does not contain a single object of interest.")
            return

    for layer_def in do_layers(params):

        # Locate a 'metadata' subdirectory inside the delivery.
        # Metadata directory name is case-insensitive, 'Metadata' and 'metadata' are both allowed.
        metadata_dirs = [d for d in params["unzip_dir"].glob('**/*')
                         if d.is_dir() and str(d).lower().endswith(METADATA_DIRNAME)]
        if len(metadata_dirs) == 0:
            status.info("The delivery does not contain the expected '{:s}' folder. The native delivery folder will be used instead.".format(METADATA_DIRNAME))
            metadata_dir = params["unzip_dir"]
        elif len(metadata_dirs) > 1:
            status.failed("Multiple folders named '{:s}' were found in the delivery.",
                        "Only one '{:s}' folder is allowed.".format(METADATA_DIRNAME))
            return
        else:
            metadata_dir = metadata_dirs[0]

        # Verify if there is one INSPIRE metadata file to check.
        # The XML file name is derived from the layer file name or from the layer name.
        xml_name_source = params.get("xml_name_source", "layer_filepath")
        if xml_name_source == "layer_name":
            xml_filepath = locate_xml_file(metadata_dir, layer_def["src_layer_name"])
        else:
            xml_filepath = locate_xml_file(metadata_dir, layer_def["src_filepath"])
        if xml_filepath is None:
            status.failed("The delivery does not contain the expected metadata file '{:s}/{:s}.xml'".format(
                metadata_dir.stem, layer_def["src_filepath"].stem))
            return

        # Validate the xml file using INSPIRE validator service
        export_prefix = "s{:02d}_{:s}_inspire".format(params["step_nr"], layer_def["src_filepath"].stem)
        do_inspire_check(xml_filepath, export_prefix, params["output_dir"], status)
