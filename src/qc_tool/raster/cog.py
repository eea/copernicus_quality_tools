#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "The raster file complies with the Cloud Optimized GeoTIFF (COG) specification."
IS_SYSTEM = False

def run_check(params, status):
    import subprocess
    import os
    import re

    from qc_tool.raster.helper import do_raster_layers

    for layer_def in do_raster_layers(params):

        status.info("Using GDAL COG validator.")
        qc_tool_raster_dir = os.path.dirname(__file__)
        cmd = ["python3", os.path.join(qc_tool_raster_dir, "validate_cloud_optimized_geotiff.py"), "--full-check=yes", str(layer_def["src_filepath"])]
        try:
            cog_validation_output = str(subprocess.check_output(cmd, stderr=subprocess.STDOUT))
        except subprocess.CalledProcessError as e:
            cog_validation_output = str(e.output)

        cog_validation_output = cog_validation_output.replace(r"\n\n", "___").replace(r"\n", "")

        if "The following warnings were found:" in cog_validation_output:
            warnings_regex = "The following warnings were found: - (.+?)___"
            m = re.search(warnings_regex, cog_validation_output)
            if m:
                status.info("The following warnings were found:")
                found = m.group(1)
                for warning_message in found.split(" - "):
                    status.info("- {}".format(warning_message))

        if "The following errors were found:" in cog_validation_output:
            errors_regex = "The following errors were found: - (.+?)___"
            m = re.search(errors_regex, repr(cog_validation_output))
            if m:
                status.failed("The following errors were found:")
                found = m.group(1)
                for error_message in found.split(" - "):
                    status.failed("- {}".format(error_message))

        if "is NOT a valid cloud optimized GeoTIFF" in cog_validation_output:
            status.failed(
                "The raster {:s} is NOT a valid cloud optimized GeoTIFF.".format(str(layer_def["src_layer_name"])))
        if "is a valid cloud optimized GeoTIFF" in cog_validation_output:
            status.info(
                "The raster {:s} is a valid cloud optimized GeoTIFF.".format(str(layer_def["src_layer_name"])))
