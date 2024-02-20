#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import re


DESCRIPTION = "Attribute table is composed of prescribed attributes."
IS_SYSTEM = False

def read_vatdbf(vatdbf_filepath):
    try:
        import osgeo.ogr as ogr
        ds = ogr.Open(str(vatdbf_filepath))
        layer = ds.GetLayer()
        return [field_defn.name for field_defn in layer.schema]
    except:
        return None

def read_gtiff_attributes(gtiff_filepath):
    # try:
    import osgeo.gdal as gdal
    ds = gdal.Open(str(gtiff_filepath))
    band = ds.GetRasterBand(1)
    rat = band.GetDefaultRAT()
    return [rat.GetNameOfCol(icol) for icol in range(rat.GetColumnCount())]
    # except:
    #     return None

def run_check(params, status):
    from qc_tool.raster.helper import do_raster_layers

    for layer_def in do_raster_layers(params):
        attr_names = read_gtiff_attributes(layer_def["src_filepath"])
        if attr_names is None:
            # check for .vat.dbf file existence
            dbf_filename = "{:s}.vat.dbf".format(layer_def["src_filepath"].name)
            dbf_filepath = layer_def["src_filepath"].with_name(dbf_filename)

            if not dbf_filepath.is_file():
                status.failed("Attribute table for layer {:s} is missing.".format(layer_def["src_filepath"].name))
                continue

            attr_names = read_vatdbf(dbf_filepath)
        missing_attr_regexes = []
        for attr_regex in params["attribute_regexes"]:
            is_missing = True
            for attr_name in attr_names:
                mobj = re.match("{:s}$".format(attr_regex), attr_name, re.IGNORECASE)
                if mobj is not None:
                    is_missing = False
                    break
            if is_missing:
                missing_attr_regexes.append(attr_regex)
        if len(missing_attr_regexes) > 0:
            missing_attr_message = ", ".join(missing_attr_regexes)
            status.failed("Raster attribute table {:s} has missing attributes: {:s}."
                          .format(dbf_filepath.name, missing_attr_message))
