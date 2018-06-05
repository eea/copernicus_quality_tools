#! /usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Check colors in the color table
"""

from osgeo import gdal

from qc_tool.wps.registry import register_check_function

@register_check_function(__name__, "Colors in the color table match product specification")
def run_check(filepath, params):
    """
    :param colors: a dictionary of raster values and associated [r,g,b] colors
    :return: status + message
    """
    ds = gdal.Open(filepath)

    if ds is None:
        return {"status": "aborted",
                "message": "The raster {:s} could not be opened.".format(filepath)}

    # get the number of bands
    num_bands = ds.RasterCount
    if num_bands != 1:
        return {"status": "failed",
                "message": "The raster has {:d} bands. \
                            expected number of bands is one.".format(num_bands)}

    # get the DataType of the band ("Byte" means 8-bit depth)
    band = ds.GetRasterBand(1)

    # check the color table of the band
    ct = band.GetRasterColorTable()
    if ct is None:
        return {"status": "failed",
                "message": "The raster {:s} does not have a \
                            color table.".format(filepath)}

    # read-in the actual color table into a dictionary
    color_table_count = ct.GetCount()
    actual_colours = {}
    for i in range( 0, color_table_count):
        entry = ct.GetColorEntry(i)
        if not entry:
            continue
        # converting a GDAL ColorEntry (r,g,b,a) tuple to a [r,g,b] list
        actual_colours[str(i)] = list(entry[0:3])

    #return {"status": "failed",
    #        "message": "actual_colours: {:s} bands. \
    #                    ...".format(str(actual_colours))}

    # compare expected color table with the actual color table
    missing_codes = []
    incorrect_colours = []
    expected_colours = params["colours"]
    for code, colour in expected_colours.items():
        if code not in  actual_colours:
            missing_codes.append(code)
        elif expected_colours[code] != actual_colours[code]:
            incorrect_colours.append({"class":code,
                                      "expected": expected_colours[code],
                                      "actual": actual_colours[code]})
    print(incorrect_colours)
    print(missing_codes)

    # report raster values with missing entries in the colour table
    if len(missing_codes) > 0:
        return {"status": "failed",
                "message": "The raster colour table does not have entries for raster values \
                            {:s}".format(", ".join(missing_codes))}

    # report color mismatches between expected and actual colour table
    if len(incorrect_colours) > 0:
        colour_reports = []
        for c in incorrect_colours:
            colour_reports.append("value:{:s}, expected RGB:{:s}, actual RGB:{:s}".format(c))
        return {"status": "failed",
                "message": "The raster colour table has some incorrect colours. \
                            {:s}".format("; ".join(colour_reports))}
    else:
        return {"status": "ok"}
