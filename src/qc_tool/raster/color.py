#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import time
from pathlib import Path


DESCRIPTION = "Color table is in accord with specification."
IS_SYSTEM = False


def run_check(params, status):
    import osgeo.gdal as gdal

    geotiff_name = params["filepath"].name

    ds = gdal.Open(str(params["filepath"]))
    band = ds.GetRasterBand(1)

    # check the color table of the band
    ct = band.GetRasterColorTable()
    if ct is None:
        status.failed("The raster {:s} has embedded color table missing.".format(geotiff_name))
        return

    # read-in the actual color table into a dictionary
    color_table_count = ct.GetCount()
    actual_colors = {}
    for i in range( 0, color_table_count):
        entry = ct.GetColorEntry(i)
        if not entry:
            continue
        # converting a GDAL ColorEntry (r,g,b,a) tuple to a [r,g,b] list
        actual_colors[str(i)] = list(entry[0:3])

    # compare expected color table with the actual color table
    missing_codes = []
    incorrect_colors = []
    expected_colors = params["colors"]
    for code, color in expected_colors.items():
        if code not in  actual_colors:
            missing_codes.append(code)
        elif expected_colors[code] != actual_colors[code]:
            incorrect_colors.append({"class":code,
                                      "expected": expected_colors[code],
                                      "actual": actual_colors[code]})

    # report raster values with missing entries in the color table
    if len(missing_codes) > 0:
        status.failed("The raster color table embedded in {:s} does not have entries for raster values {:s}."
                      .format(geotiff_name, ", ".join(missing_codes)))
        return

    # report color mismatches between expected and actual color table
    if len(incorrect_colors) > 0:
        color_reports = []
        for c in incorrect_colors:
            color_reports.append("value:{0}, expected RGB:{1}, actual RGB:{2}"
                                  .format(c["class"], c["expected"], c["actual"]))
        status.failed("The raster color table has some incorrect colors. {:s}"
                      .format("; ".join(color_reports)))
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
        status.failed("The expected color table text file {:s} or {:s} is missing.".format(clr_filename1, clr_filename2))
        return

    # read-in the actual tif.clr color table into a dictionary
    lines = clr_filepath.read_text().splitlines()
    actual_colors = {}
    for line in lines:
        line = line.strip()
        if line == "":
            continue
        items = line.split(" ")
        if len(items) != 4:
            status.failed("The color table text file {:s} is in incorrect format.".format(clr_filename))
            return
        index = items[0]
        try:
            rgb = [int(items[1]), int(items[2]), int(items[3])]
        except ValueError as ex:
            status.failed("The color table {:s} is in incorrect format.".format(clr_filename))
            return
        actual_colors[index] = rgb

    # Check colors in .tif.clr file
    missing_codes = []
    incorrect_colors = []
    expected_colors = params["colors"]
    for code, color in expected_colors.items():
        if code not in actual_colors:
            missing_codes.append(code)
        elif expected_colors[code] != actual_colors[code]:
            incorrect_colors.append({"class": code,
                                      "expected": expected_colors[code],
                                      "actual": actual_colors[code]})

    # report raster values with missing entries in the color table
    if len(missing_codes) > 0:
        status.failed("The raster color table text file {:s} does not have entries for raster values {:s}."
                      .format(clr_filename, ", ".join(missing_codes)))
        return

    # report color mismatches between expected and actual color table
    if len(incorrect_colors) > 0:
        color_reports = []
        for c in incorrect_colors:
            color_reports.append(
                "value:{0}, expected RGB:{1}, actual RGB:{2}".format(c["class"], c["expected"], c["actual"]))
        status.failed("The raster color text file {:s} has some incorrect colors. {:s}"
                      .format(clr_filename, "; ".join(color_reports)))
        return
