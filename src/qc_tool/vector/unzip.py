#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from qc_tool.common import validate_zip_archive


DESCRIPTION = "Delivery file can be unzipped."
IS_SYSTEM = True

# Validators run in declaration order before extraction. Add vector-specific
# archive checks here without changing the shared extraction implementation.
ZIP_VALIDATORS = (
    validate_zip_archive,
)


def run_check(params, status):
    from qc_tool.vector.helper import do_unzip

    # Keep validation owned by this check module. New vector ZIP validators can
    # be added to ZIP_VALIDATORS without changing the shared unzip helper.
    try:
        for validator in ZIP_VALIDATORS:
            validator(params["filepath"])
    except Exception as ex:
        status.aborted("Error unzipping file {:s}, reason: {:s}".format(params["filepath"].name, str(ex)))
        return

    # Vector layers are unzipped to the temporary directory v_unzip.d.
    do_unzip(params["filepath"], params["tmp_dir"].joinpath("v_unzip.d"), status)
