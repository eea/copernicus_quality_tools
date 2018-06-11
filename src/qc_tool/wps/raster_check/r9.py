#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Pixel values check.
"""

import gdal

from qc_tool.wps.registry import register_check_function

@register_check_function(__name__, "Pixel values check.")
def run_check(filepath, params):
    """
    Pixel values check.
    :param filepath: pathname to data source
    :param params: configuration
    :return: status + message
    """

    # enable gdal to use exceptions
    gdal.UseExceptions()

    try:
        ds_open = gdal.Open(filepath)
        if ds_open is None:
            return {"status": "failed",
                    "message": "The file can not be opened."}
    except:
        return {"status": "failed",
                "message": "The file can not be opened."}

    # get dictionary of pixel 'codes-counts'
    ds_band = ds_open.GetRasterBand(1)
    counts = ds_band.GetHistogram()
    codes = range(len(counts))
    hist = dict(zip(codes, counts))

    # get list of 'used' codes (with non-zero pixel count)
    nodata = int(ds_band.GetNoDataValue())
    used_codes = [i for i in hist if hist[i] != 0]
    if nodata in used_codes:
        used_codes.remove(nodata)

    # check particular codes against given list of valid codes
    invalid_codes = list()
    for code in used_codes:
        if code not in params["validcodes"]:
            invalid_codes.append(str(code))

    if not invalid_codes:
        return {"status": "ok"}
    else:
        invalid_codes_str = ', '.join(invalid_codes)
        return {"status": "failed",
                "message": "Pixels contain invalid codes: {:s}.".format(invalid_codes_str)}
