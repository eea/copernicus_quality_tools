#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import time

from pathlib import Path
from osgeo import gdal

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    ds = gdal.Open(str(params["filepath"]))

    geotiff_name = params["filepath"].name

    if ds is None:
        status.aborted("The raster {:s} could not be opened.".format(geotiff_name))
        return

    # get the number of bands
    num_bands = ds.RasterCount
    if num_bands != 1:
        status.failed("The raster has {:d} bands. The expected number of bands is one.".format(num_bands))
        return

    # get the DataType of the band ("Byte" means 8-bit depth)
    band = ds.GetRasterBand(1)

    # check the color table of the band
    ct = band.GetRasterColorTable()
    if ct is None:
        status.failed("The raster {:s} has embedded color table missing.".format(geotiff_name))
        return

    # read-in the actual color table into a dictionary
    color_table_count = ct.GetCount()
    actual_colours = {}
    for i in range( 0, color_table_count):
        entry = ct.GetColorEntry(i)
        if not entry:
            continue
        # converting a GDAL ColorEntry (r,g,b,a) tuple to a [r,g,b] list
        actual_colours[str(i)] = list(entry[0:3])

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

    # report raster values with missing entries in the colour table
    if len(missing_codes) > 0:
        status.failed("The raster colour table embedded in {:s} does not have entries for raster values {:s}."
                      .format(geotiff_name, ", ".join(missing_codes)))
        return

    # report color mismatches between expected and actual colour table
    if len(incorrect_colours) > 0:
        colour_reports = []
        for c in incorrect_colours:
            colour_reports.append("value:{0}, expected RGB:{1}, actual RGB:{2}".format(c["class"], c["expected"], c["actual"]))
        status.failed("The raster colour table has some incorrect colours. {:s}".format("; ".join(colour_reports)))
        return

    # Check existence of a .tif.clr or .clr file.
    clr_name1 = str(params["filepath"]).replace(".tif", ".clr")
    clr_filepath1 = Path(clr_name1)
    clr_filename1 = clr_filepath1.name

    clr_name2 = str(params["filepath"]).replace(".tif", ".tif.clr")
    clr_filepath2 = Path(clr_name2)
    clr_filename2 = clr_filepath2.name

    if clr_filepath1.is_file():
        clr_filepath = clr_filepath1
        clr_filename = clr_filename1
    elif clr_filepath2.is_file():
        clr_filepath = clr_filepath2
        clr_filename = clr_filename2
    else:
        status.failed("The expected colour table text file {:s} or {:s} is missing.".format(clr_filename1, clr_filename2))
        return

    # read-in the actual tif.clr color table into a dictionary
    lines = [line.rstrip('\n') for line in open(str(clr_filepath))]
    actual_colours = {}
    for line in lines:
        items = line.split(" ")
        if len(items) != 4:
            status.failed("The colour table text file {:s} is in incorrect format.".format(clr_filename))
            return
        index = items[0]
        rgb = [int(items[1]), int(items[2]), int(items[3])]
        actual_colours[index] = rgb

    # Check colours in .tif.clr file
    missing_codes = []
    incorrect_colours = []
    expected_colours = params["colours"]
    for code, colour in expected_colours.items():
        if code not in actual_colours:
            missing_codes.append(code)
        elif expected_colours[code] != actual_colours[code]:
            incorrect_colours.append({"class": code,
                                      "expected": expected_colours[code],
                                      "actual": actual_colours[code]})

    # report raster values with missing entries in the colour table
    if len(missing_codes) > 0:
        status.failed("The raster colour table text file {:s} does not have entries for raster values {:s}."
                      .format(clr_filename, ", ".join(missing_codes)))
        return

    # report color mismatches between expected and actual colour table
    if len(incorrect_colours) > 0:
        colour_reports = []
        for c in incorrect_colours:
            colour_reports.append(
                "value:{0}, expected RGB:{1}, actual RGB:{2}".format(c["class"], c["expected"], c["actual"]))
        status.failed("The raster colour text file {:s} has some incorrect colours. {:s}"
                      .format(clr_filename, "; ".join(colour_reports)))
        return


