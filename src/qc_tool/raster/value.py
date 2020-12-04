#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Pixels have specific values."
IS_SYSTEM = False


def run_check(params, status):
    import osgeo.gdal as gdal
    from qc_tool.raster.helper import do_raster_layers

    # extract validcodes parameter. An item in validcodes can be a single number or a range.
    valid_codes = []
    for validcode_item in params["validcodes"]:
        if type(validcode_item) is list:
            valid_codes = valid_codes + list(range(validcode_item[0], validcode_item[1] + 1))
        else:
            valid_codes.append(validcode_item)


    for layer_def in do_raster_layers(params):
        ds = gdal.Open(str(layer_def["src_filepath"]))

        # get dictionary of pixel 'codes-counts'
        ds_band = ds.GetRasterBand(1)
        counts = ds_band.GetHistogram(approx_ok=False)
        codes = range(len(counts))
        hist = dict(zip(codes, counts))

        # get list of 'used' codes (with non-zero pixel count)
        used_codes = [i for i in hist if hist[i] != 0]

        # check particular codes against given list of valid codes
        invalid_codes = list()
        for code in used_codes:
            if code not in valid_codes:
                invalid_codes.append(str(code))
        if len(invalid_codes) > 0:
            invalid_codes_str = ', '.join(invalid_codes)
            status.failed("Layer {:s} has pixels with invalid values: {:s}."
                          .format(layer_def["src_layer_name"], invalid_codes_str))
