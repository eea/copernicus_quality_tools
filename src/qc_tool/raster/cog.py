#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "The raster file complies with the Cloud Optimized GeoTIFF (COG) specification."
IS_SYSTEM = False

def run_check(params, status):
    import subprocess
    import os
    import re

    from qc_tool.raster.helper import do_raster_layers

    strict = params.get("strict", False)

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

        if strict:
            COG_MAX_HEADER_BYTES = 1024 * 1024  # 1 MB

            # Check header size reported by validate_cloud_optimized_geotiff.py.
            header_size_regex = r"The size of all IFD headers is (\d+) bytes"
            m = re.search(header_size_regex, cog_validation_output)
            if m:
                header_size = int(m.group(1))
                if header_size >= COG_MAX_HEADER_BYTES:
                    status.failed(
                        "header size {:d} is bigger than allowed header size of 1MB.".format(header_size))

            # Additional header size check using cog_header.py.
            from qc_tool.raster.cog_header import analyze as analyze_cog_header
            cog_header_result = analyze_cog_header(str(layer_def["src_filepath"]))
            if cog_header_result is not None:
                cog_header_size = cog_header_result["header_bytes"]
                if cog_header_size >= COG_MAX_HEADER_BYTES:
                    status.failed(
                        "header size {:d} is bigger than allowed header size of 1MB.".format(cog_header_size))
