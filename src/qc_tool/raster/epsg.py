#! /usr/bin/env python3
# -*- coding: utf-8 -*-


from osgeo import gdal
from osgeo import osr


def run_check(params, status):
    dataset = gdal.Open(str(params["filepath"]))

    srs = osr.SpatialReference(dataset.GetProjection())
    if srs is None or srs.IsProjected() == 0:
        status.failed("The raster file has no projected coordinate system associated.")
        return

    # Search EPSG authority code
    authority_name = srs.GetAuthorityName(None)
    authority_code = srs.GetAuthorityCode(None)

    if authority_name == "EPSG" and authority_code is not None:
        # compare EPSG code using the root-level EPSG authority
        if authority_code not in map(str, params["epsg"]):
            status.aborted("Raster has illegal EPSG code {:s}.".format(str(authority_code)))
            return
    else:
        # If the EPSG code is not detected, try to compare if the actual and expected SRS instances represent
        # the same spatial reference system.
        srs_match = False
        allowed_codes = params["epsg"]
        for allowed_code in allowed_codes:
            expected_srs = osr.SpatialReference()
            expected_srs.ImportFromEPSG(allowed_code)
            if srs.IsSame(expected_srs):
                srs_match = True
                break

        if not srs_match:
            allowed_codes_msg = ", ".join(map(str, params["epsg"]))
            status.aborted("The SRS of the raster is not in the list of allowed spatial reference systems. "
                           "detected SRS: {:s}, list of allowed SRS's: {:s} ".format(srs.ExportToWkt(), allowed_codes_msg))
