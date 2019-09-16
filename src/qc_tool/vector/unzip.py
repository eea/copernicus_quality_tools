#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from qc_tool.vector.helper import do_unzip


DESCRIPTION = "Delivery file can be unzipped."
IS_SYSTEM = True


def run_check(params, status):
    # Vector layers are unzipped to the temporary directory v_unzip.d.
    do_unzip(params["filepath"], params["tmp_dir"].joinpath("v_unzip.d"), status)

