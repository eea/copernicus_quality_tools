#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import os

DESCRIPTION = "The attribute order complies with the specification."
IS_SYSTEM = False


def run_check(params, status):
    from osgeo.gdal import OpenEx

    from qc_tool.vector.helper import do_layers


    # Check if the current delivery is excluded from vector checks
    if "skip_vector_checks" in params:
        if params["skip_vector_checks"]:
            status.info("The delivery has been excluded from vector.attribute check because the vector data source does not contain a single object of interest.")
            return

    for layer_def in do_layers(params):

        ds = OpenEx(str(layer_def["src_filepath"]), 0, open_options=["AUTODETECT_TYPE=YES", "SEPARATOR=SEMICOLON"])
        layer = ds.GetLayerByName(layer_def["src_layer_name"])
        attribute_order_defined = [attr_name.lower() for attr_name in params["attribute_order"]]

        layer_attributes = [field_defn.name.lower() for field_defn in layer.schema]

        is_subset = set(attribute_order_defined).issubset(layer_attributes)

        if not is_subset:
            missing_items = set(attribute_order_defined) - set(layer_attributes)
            status.failed("Layer {:s} does not contain some of the required attributes (the following required attributes are missing: '{:s}')".format(
                layer_def["src_layer_name"],
                "', '".join(list(missing_items))))

        attribute_order_layer = [attr_name for attr_name in layer_attributes if attr_name in attribute_order_defined]

        order_is_correct = attribute_order_layer == attribute_order_defined

        if not order_is_correct:
            status.failed(
                "The order of attributes in the layer {:s} does not match the specification. "
                "Order of attributes in the checked layer: '{:s}'. "
                "Order of attributes according to specification: '{:s}'.".format(
                    layer_def["src_layer_name"],
                    "', '".join(list(attribute_order_layer)),
                    "', '".join(list(attribute_order_defined))
                )
            )
