#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Metadata are in accord with INSPIRE specification."
IS_SYSTEM = False

METADATA_DIRNAME = "metadata"


def locate_xml_file(metadata_folder_path, layer_filepath, layer_name=None):
    # The INSPIRE XML file can be LAYER.xml or LAYER_metadata.xml.
    # Search in metadata_folder_path and all subdirectories.
    if layer_name:
        xml_names = [layer_name + "_metadata.xml", layer_name + ".xml"]
    else:
        xml_names = [layer_filepath.stem + "_metadata.xml", layer_filepath.stem + ".xml"]

    xml_files_by_name_lower = None
    for xml_name in xml_names:
        matches = list(metadata_folder_path.rglob(xml_name))
        if matches:
            return matches[0]

        # Linux filesystems are case-sensitive; allow case-insensitive lookup
        # so layer name casing does not break metadata discovery.
        if xml_files_by_name_lower is None:
            xml_files_by_name_lower = {}
            all_xml_files = sorted(
                [p for p in metadata_folder_path.glob("**/*") if p.is_file() and p.suffix.lower() == ".xml"],
                key=lambda p: str(p).lower(),
            )
            for xml_file in all_xml_files:
                xml_files_by_name_lower.setdefault(xml_file.name.lower(), xml_file)

        xml_file = xml_files_by_name_lower.get(xml_name.lower())
        if xml_file:
            return xml_file
    return None


def get_expected_xml_names(layer_filepath, layer_name=None):
    # Expected INSPIRE metadata names can be either <name>.xml or <name>_metadata.xml.
    stems = []
    if layer_name:
        stems.append(layer_name)
    if layer_filepath.stem not in stems:
        stems.append(layer_filepath.stem)

    expected = []
    for stem in stems:
        expected.append(stem + ".xml")
        expected.append(stem + "_metadata.xml")
    return expected


def run_check(params, status):
    from qc_tool.vector.helper import do_inspire_check
    from qc_tool.vector.helper import do_layers
    from qc_tool.common import CONFIG

    # Check if the current delivery is excluded from vector checks
    if "skip_vector_checks" in params:
        if params["skip_vector_checks"]:
            status.info("The delivery has been excluded from vector.inspire check because the vector data source does not contain a single object of interest.")
            return
        
    use_lightweight_validator = CONFIG.get("use_lightweight_validator", False)
    if use_lightweight_validator:
        status.info("Using built-in geonetwork-based lightweight validator instead of INSPIRE validator service.")

    for layer_def in do_layers(params):

        # Locate a 'metadata' subdirectory inside the delivery.
        # Metadata directory name is case-insensitive, 'Metadata' and 'metadata' are both allowed.
        metadata_dirs = [d for d in params["unzip_dir"].glob('**/*')
                         if d.is_dir() and str(d).lower().endswith(METADATA_DIRNAME)]
        if len(metadata_dirs) == 0:
            metadata_dir = params["unzip_dir"]
        elif len(metadata_dirs) > 1:
            status.failed("Multiple folders named '{:s}' were found in the delivery.",
                        "Only one '{:s}' folder is allowed.".format(METADATA_DIRNAME))
            return
        else:
            metadata_dir = metadata_dirs[0]

        # Verify if there is one INSPIRE metadata file to check.
        # The XML file name is derived from the layer file name or from the layer name.
        layer_name = layer_def.get("src_layer_name", layer_def["src_filepath"].stem)
        xml_name_source = params.get("xml_name_source", "layer_filepath")
        if xml_name_source == "layer_name":
            xml_filepath = locate_xml_file(metadata_dir, layer_def["src_filepath"], layer_name)
            if xml_filepath is None:
                xml_filepath = locate_xml_file(metadata_dir, layer_def["src_filepath"])
        else:
            xml_filepath = locate_xml_file(metadata_dir, layer_def["src_filepath"])
            if xml_filepath is None:
                # Backward-compatible fallback: many products name XML by layer name.
                xml_filepath = locate_xml_file(metadata_dir, layer_def["src_filepath"], layer_name)
        if xml_filepath is None:
            expected_xml_names = get_expected_xml_names(layer_def["src_filepath"], layer_name)
            status.failed("The delivery does not contain expected metadata file. Looked for: {:s}".format(
                ", ".join(expected_xml_names)))
            continue

        # Validate the xml file using INSPIRE validator service
        export_prefix = "s{:02d}_{:s}_{:s}_inspire".format(params["step_nr"], layer_def["src_filepath"].stem, layer_name)
        do_inspire_check(xml_filepath, export_prefix, params["output_dir"], status, lightweight_validator=use_lightweight_validator)
