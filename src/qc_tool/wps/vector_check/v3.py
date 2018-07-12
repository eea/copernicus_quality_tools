#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import re

from osgeo import ogr

from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):
    attr_regexes = [re.compile("{:s}$".format(attr_regex)) for attr_regex in params["attribute_regexes"]]
    for layer_name, layer_filepath in params["layer_sources"]:
        ds = ogr.Open(str(layer_filepath))
        layer = ds.GetLayerByName(layer_name)
        attr_names = [field_defn.name for field_defn in layer.schema]
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
            status.add_message("Layer {:s} has missing attributes: {:s}.".format(layer_name, missing_attr_message))
