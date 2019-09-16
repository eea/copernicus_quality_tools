#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from qc_tool.vector.helper import do_unzip


DESCRIPTION = "Delivery file can be unzipped."
IS_SYSTEM = True


def run_check(params, status):
    # Raster layers are unzipped to the temporary directory r_unzip.d.
    do_unzip(params["filepath"], params["tmp_dir"].joinpath("r_unzip.d"), status)
