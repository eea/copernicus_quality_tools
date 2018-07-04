#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from zipfile import ZipFile

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params):
    zip_filepath = params["filepath"]
    extract_dir = params["tmp_dir"].joinpath("v_unzip.d")
    extract_dir.mkdir()
    
    # Unzip the source zip file.
    try:
        with ZipFile(str(zip_filepath)) as zip_file:
            zip_file.extractall(path=str(extract_dir))
    except Exception as ex:
        return {"status": "aborted",
                "message": "Error unzipping file {:s}.".format(zip_filepath.filename)}

    # Find gdb directory.
    gdb_filepaths = [path for path in list(extract_dir.iterdir()) if path.name.lower().endswith(".gdb")]
    if len(gdb_filepaths) != 1 or not gdb_filepaths[0].is_dir():
        return {"status": "aborted",
                "message": "There must be exactly one .gdb directory in the zip file."}

    return {"status": "ok",
            "params": {"filepath": gdb_filepaths[0]}}
