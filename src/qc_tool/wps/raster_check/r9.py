#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from osgeo import gdal

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    # enable gdal to use exceptions
    gdal.UseExceptions()

    try:
        ds_open = gdal.Open(str(params["filepath"]))
        if ds_open is None:
            status.failed("The file can not be opened.")
            return
    except:
        status.failed("The file can not be opened.")
        return

    # get dictionary of pixel 'codes-counts'
    ds_band = ds_open.GetRasterBand(1)
    counts = ds_band.GetHistogram()
    codes = range(len(counts))
    hist = dict(zip(codes, counts))

    # get list of 'used' codes (with non-zero pixel count)
    used_codes = [i for i in hist if hist[i] != 0]

    # check particular codes against given list of valid codes
    invalid_codes = list()
    for code in used_codes:
        if code not in params["validcodes"]:
            invalid_codes.append(str(code))
    if len(invalid_codes) > 0:
        invalid_codes_str = ', '.join(invalid_codes)
        status.failed("Pixels contain invalid codes: {:s}.".format(invalid_codes_str))
