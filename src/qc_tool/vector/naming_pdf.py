#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Naming is in accord with specification."
IS_SYSTEM = False


def run_check(params, status):

    from qc_tool.vector.helper import LayerDefsBuilder
    from qc_tool.vector.helper import extract_aoi_code
    from qc_tool.vector.helper import extract_epsg_code
    from qc_tool.vector.helper import find_pdfs


    # Find PDF (.pdf) layers.
    pdf_file_infos = find_pdfs(params["unzip_dir"], status)


    # Check if delivery contains any PDF files.
    if len(pdf_file_infos) == 0:
        status.aborted("No PDF files were found in the delivery.")
        return

    # Read all PDF file infos into builder.
    builder = LayerDefsBuilder(status)
    for pdf_file_info in pdf_file_infos:
        builder.add_layer_info(pdf_file_info["src_filepath"], pdf_file_info["src_filename"])

    # Build layer defs for all documents (PDF files).
    for layer_alias, layer_regex in params["document_names"].items():
        builder.extract_layer_def(layer_regex, layer_alias)


    # TODO: decide how to deal with excesive layers
    # # Check excessive layers.
    # excessive_layers_allowed = params.get("excessive_layers_allowed", False)
    # if not excessive_layers_allowed:
    #     builder.check_excessive_layers()

    # Extract AOI code and compare it to pre-defined list.
    aoi_code = None
    if "aoi_codes" in params and len(params["aoi_codes"]) > 0:
        if params["aoi_codes"][0] == "*":
            preserve_aoicode_case = True
            compare_aoi_codes = False
        else:
            preserve_aoicode_case = False
            compare_aoi_codes = True
        aoi_code = extract_aoi_code(builder.layer_defs, params["document_names"], params["aoi_codes"], status,
                                    preserve_aoicode_case=preserve_aoicode_case, compare_aoi_codes=compare_aoi_codes)


    # Extract EPSG code and compare it to pre-defined list.
    name_epsg = None
    if "epsg_codes" in params and len(params["epsg_codes"]) > 0:
        compare_epsg_codes = True
        name_epsg = extract_epsg_code(builder.layer_defs, params["document_names"], params["epsg_codes"], status,
                                      compare_epsg_codes=compare_epsg_codes)

    checked_pdf_file_names = "', '". join([product["src_layer_name"] for alias, product in builder.layer_defs.items()])
    status.info(f"PDF file names: '{checked_pdf_file_names}' have been successfully checked.")
    status.info(f"AOI code detected from PDF file names: {aoi_code}")
    status.info(f"EPSG code detected from PDF file names: {name_epsg}")


