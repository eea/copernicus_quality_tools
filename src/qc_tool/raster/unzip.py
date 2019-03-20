#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import os
from zipfile import ZipFile


DESCRIPTION = "Delivery file can be unzipped."
IS_SYSTEM = True


def run_check(params, status):
    zip_filepath = params["filepath"]
    unzip_dir = params["tmp_dir"].joinpath("r_unzip.d")
    unzip_dir.mkdir()
    
    # Unzip the source zip file.
    try:
        with ZipFile(str(zip_filepath)) as zip_file:
            zip_file.extractall(path=str(unzip_dir))
    except Exception as ex:
        status.aborted("Error unzipping file {:s}.".format(zip_filepath.filename))
        return

    status.add_params({"unzip_dir": unzip_dir})
