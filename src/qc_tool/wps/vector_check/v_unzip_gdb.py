#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from zipfile import ZipFile

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    zip_filepath = params["filepath"]
    extract_dir = params["tmp_dir"].joinpath("v_unzip_gdb.d")
    extract_dir.mkdir()

    # Unzip the source zip file.
    try:
        with ZipFile(str(zip_filepath)) as zip_file:
            zip_file.extractall(path=str(extract_dir))
    except Exception as ex:
        status.aborted()
        status.add_message("Error unzipping file {:s}.".format(zip_filepath.name))
        return

    # Find gdb directory.
    gdb_filepaths = [path for path in list(extract_dir.iterdir()) if path.suffix.lower() == ".gdb"]
    if len(gdb_filepaths) != 1 or not gdb_filepaths[0].is_dir():
        status.aborted()
        status.add_message("There must be exactly one .gdb directory in the zip file.")
        return

    status.add_params({"filepath": gdb_filepaths[0]})
