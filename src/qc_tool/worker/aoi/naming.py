"""Generic AOI naming adapters shared by raster and vector checks.

The functions preserve each product's raw AOI value for its downstream QC
parameters. Only the status property published to the worker result crosses
the canonical metadata boundary.
"""

import re

from qc_tool.aoi import AOI_CODE_KEY
from qc_tool.aoi import aoi_codes_equivalent
from qc_tool.aoi import extract_aoi_code_from_groups
from qc_tool.aoi import has_aoi_code_capture
from qc_tool.aoi import with_canonical_aoi_capture

from .metadata import invalidate_aoi_metadata


def check_gdb_filename(gdb_filepath, gdb_filename_regex, aoi_code, status):
    """Validate an optional AOI capture in a geodatabase filename."""

    match = re.compile(gdb_filename_regex, re.IGNORECASE).search(
        gdb_filepath.name
    )
    if match is None:
        status.aborted(
            "Geodatabase filename {:s} is not in accord with specification: "
            "'{:s}'.".format(gdb_filepath.name, gdb_filename_regex)
        )
        invalidate_aoi_metadata(status)
        return False

    if not has_aoi_code_capture(gdb_filename_regex) or aoi_code is None:
        return True

    try:
        detected_aoi_code = extract_aoi_code_from_groups(match.groupdict())
    except ValueError:
        status.aborted(
            "Geodatabase filename {:s} contains conflicting AOI codes."
            .format(gdb_filepath.name)
        )
        invalidate_aoi_metadata(status)
        return False
    if detected_aoi_code is None:
        status.aborted(
            "Geodatabase filename {:s} does not contain AOI code."
            .format(gdb_filepath.name)
        )
        invalidate_aoi_metadata(status)
        return False
    if not aoi_codes_equivalent(detected_aoi_code, aoi_code):
        status.aborted(
            "Geodatabase filename AOI code '{:s}' does not match AOI code "
            "of the layers: '{:s}'".format(detected_aoi_code, aoi_code)
        )
        invalidate_aoi_metadata(status)
        return False
    return True


def extract_aoi_code(
    layer_defs,
    layer_regexes,
    expected_aoi_codes,
    status,
    preserve_aoicode_case=False,
    compare_aoi_codes=True,
):
    """Validate layer captures and return the product-specific raw AOI."""

    layer_aoi_codes = []
    invalid_aoi_code = False
    for layer_alias, layer_def in layer_defs.items():
        layer_name = layer_def["src_layer_name"]
        groups = layer_def.get("groups")
        if groups is None:
            layer_regex = layer_regexes[layer_alias]
            flags = re.IGNORECASE if preserve_aoicode_case else 0
            match = re.match(
                layer_regex,
                layer_name if preserve_aoicode_case else layer_name.lower(),
                flags,
            )
            if match is None:
                status.aborted(
                    "Layer {:s} has illegal name: {:s}.".format(
                        layer_alias,
                        layer_name,
                    )
                )
                invalid_aoi_code = True
                continue
            groups = match.groupdict()
        try:
            groups = with_canonical_aoi_capture(groups)
        except ValueError:
            status.aborted(
                "Layer {:s} contains conflicting AOI code captures."
                .format(layer_name)
            )
            invalid_aoi_code = True
            continue

        aoi_code = groups.get(AOI_CODE_KEY)
        if aoi_code is None:
            status.aborted(
                "Layer {:s} does not contain AOI code.".format(layer_name)
            )
            invalid_aoi_code = True
            continue
        if not preserve_aoicode_case:
            aoi_code = aoi_code.casefold()
        layer_aoi_codes.append(aoi_code)

        if compare_aoi_codes and not any(
            aoi_codes_equivalent(aoi_code, expected_aoi_code)
            for expected_aoi_code in expected_aoi_codes
        ):
            status.aborted(
                "Layer {:s} has illegal AOI code {:s}.".format(
                    layer_name,
                    aoi_code,
                )
            )
            invalid_aoi_code = True

    if not layer_aoi_codes:
        status.aborted("AOI code could not be detected from any layer name.")
        invalidate_aoi_metadata(status)
        return None

    first_aoi_code = layer_aoi_codes[0]
    if any(
        not aoi_codes_equivalent(first_aoi_code, candidate)
        for candidate in layer_aoi_codes[1:]
    ):
        status.aborted(
            "Layers do not have the same AOI code. Detected AOI codes: {:s}"
            .format(",".join(layer_aoi_codes))
        )
        invalidate_aoi_metadata(status)
        return None
    if invalid_aoi_code:
        invalidate_aoi_metadata(status)
        return None

    status.set_status_property(AOI_CODE_KEY, first_aoi_code)
    return first_aoi_code
