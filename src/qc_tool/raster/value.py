#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from osgeo import gdal


def run_check(params, status):
    ds = gdal.Open(str(params["filepath"]))

    # get dictionary of pixel 'codes-counts'
    ds_band = ds.GetRasterBand(1)
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
