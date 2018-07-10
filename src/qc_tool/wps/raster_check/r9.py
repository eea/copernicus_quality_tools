#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Pixel values check.
"""


from osgeo import gdal

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    """
    Pixel values check.
    :param params: configuration
    :return: status + message
    """

    # enable gdal to use exceptions
    gdal.UseExceptions()

    try:
        ds_open = gdal.Open(str(params["filepath"]))
        if ds_open is None:
            status.add_message("The file can not be opened.")
            return
    except:
        status.add_message("The file can not be opened.")
        return

    # get dictionary of pixel 'codes-counts'
    ds_band = ds_open.GetRasterBand(1)
    counts = ds_band.GetHistogram()
    codes = range(len(counts))
    hist = dict(zip(codes, counts))

    # the raster must have a valid NoDataValue entry
    nodata_obj = ds_band.GetNoDataValue()
    if nodata_obj is None:
        status.add_message("The Geotiff does not have a NoData value specified.")
        return

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
        return
    else:
        invalid_codes_str = ', '.join(invalid_codes)
        status.add_message("Pixels contain invalid codes: {:s}.".format(invalid_codes_str))
        return
