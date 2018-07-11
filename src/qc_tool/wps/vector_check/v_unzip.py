#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from zipfile import ZipFile

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    zip_filepath = params["filepath"]
    suffixes = params["suffixes"]
    extract_dir = params["tmp_dir"].joinpath("v_unzip.d")
    extract_dir.mkdir()

    # Unzip the source zip file.
    try:
        with ZipFile(str(zip_filepath)) as zip_file:
            zip_file.extractall(path=str(extract_dir))
    except Exception as ex:
        status.aborted()
        status.add_message("Error unzipping file {:s}.".format(zip_filepath.name))
        return

    # search in the tree for directories or files with all specified suffixes.
    gdb_filepaths = []
    shp_filepaths = []

    if ".gdb" in params["suffixes"]:
        gdb_filepaths = [path for path in list(extract_dir.glob("**/*"))
                         if path.suffix.lower() == ".gdb" and path.is_dir()]
    if ".shp" in params["suffixes"]:
        shp_filepaths = [path for path in list(extract_dir.glob("**/*"))
                         if path.suffix.lower() == ".shp" and path.is_file()]

    if len(gdb_filepaths) == 0 and len(shp_filepaths) == 0:
        status.aborted()
        status.add_message("There must be at least one {:s} item in the zip file.".format(" or ".join(suffixes)))
        return

    if len(gdb_filepaths) > 0 and len(shp_filepaths) > 0:
        status.aborted()
        status.add_message("There cannot be a .gdb directory and a .shp file in the same zip file.")
        return

    if len(gdb_filepaths) > 1:
        status.aborted()
        status.add_message("There cannot be more than one .gdb directory in the zip file. "
                           "Found {:d} .gdb directories.".format(len(gdb_filepaths)))
        return

    if len(gdb_filepaths) == 1:
        # one .gdb directory: status ok
        status.add_params({"filepath": gdb_filepaths[0]})
        return

    if len(shp_filepaths) > 0:
        shp_dirs = [filepath.parents[0] for filepath in shp_filepaths]
        shp_dirs = list(set(shp_dirs))

        if len(shp_dirs) == 0:
            status.aborted()
            status.add_message("All .shp files in the zip file must be inside a directory. No directory found.")

        if len(shp_dirs) > 1:
            status.aborted()
            status.add_message("All .shp files in the zip file must be in one directory. "
                               "{:d} directories found ({:s})".format(len(shp_dirs), ",".join(shp_dirs)))
            return

        else:
            # one directory with one or more .shp files: status ok
            status.add_params({"filepath": shp_dirs[0]})
            return