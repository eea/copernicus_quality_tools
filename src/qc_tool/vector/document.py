#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Delivery contains a pdf document."
IS_SYSTEM = False


def run_check(params, status):
    from qc_tool.vector.helper import find_documents

    # Find supplementary documents, e.g. {clc2024_{aoi_code}_wumeta.pdf.
    for document_alias, document_regex in params.get("documents", {}).items():
        document_regex_with_aoi = document_regex.replace("{aoi_code}", params.get("aoi_code", ""))
        document_filepaths = find_documents(params["unzip_dir"], document_regex_with_aoi)
        if not document_filepaths:
            status.failed("The delivery does not contain the expected document '{:s}'.".format(document_regex_with_aoi))
