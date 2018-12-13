#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import re

from osgeo import ogr

from qc_tool.wps.helper import do_layers
from qc_tool.wps.registry import register_check_function


OGR_TYPES = {ogr.OFTBinary: "binary",
             ogr.OFTDate: "date",
             ogr.OFTDateTime: "datetime",
             ogr.OFTInteger: "integer",
             ogr.OFTInteger64: "integer64",
             ogr.OFTInteger64List: "list-of-integer64",
             ogr.OFTIntegerList: "list-of-integer",
             ogr.OFTReal: "real",
             ogr.OFTRealList: "list-of-real",
             ogr.OFTString: "string",
             ogr.OFTStringList: "list-of-string",
             ogr.OFTTime: "time",
             ogr.OFTWideString: "wide-string",
             ogr.OFTWideStringList: "list-of-wide-string"}

ALLOWED_TYPES = {ogr.OFTInteger: "integer",
                 ogr.OFTInteger64: "integer",
                 ogr.OFTReal: "real",
                 ogr.OFTString: "string",
                 ogr.OFTWideString: "string"}



@register_check_function(__name__)
def run_check(params, status):
    for layer_def in do_layers(params):
        ds = ogr.Open(str(layer_def["src_filepath"]))
        layer = ds.GetLayerByName(layer_def["src_layer_name"])
        product_attrs = {attr_name.lower(): attr_type_name.lower()
                         for attr_name, attr_type_name in params["attributes"].items()}
        extra_attrs = {}
        for field_defn in layer.schema:
            field_name = field_defn.name.lower()
            field_type = field_defn.GetType()
            if field_type not in OGR_TYPES:
                # Field type is unknown.
                extra_attrs[field_name] = "unknown-type"
                del product_attrs[field_name]
            elif field_type not in ALLOWED_TYPES:
                # Field type is not allowed.
                extra_attrs[field_name] = OGR_TYPES[field_type]
                del product_attrs[field_name]
            elif field_name not in product_attrs:
                # Extra field.
                extra_attrs[field_name] = ALLOWED_TYPES[field_type]
            elif ALLOWED_TYPES[field_type] != product_attrs[field_name]:
                # Field does not match a type in product definition.
                extra_attrs[field_name] = ALLOWED_TYPES[field_type]
            else:
                # Field matches product definition.
                del product_attrs[field_name]
        missing_attrs = product_attrs

        if len(extra_attrs) > 0:
            status.add_message("Layer {:s} has extra attributes: {:s}."
                               .format(layer_def["src_layer_name"],
                                       ", ".join("{:s}({:s})".format(attr_name, extra_attrs[attr_name])
                                                 for attr_name in sorted(extra_attrs.keys()))))
        if len(missing_attrs) > 0:
            status.aborted()
            status.add_message("Layer {:s} has missing attributes: {:s}."
                               .format(layer_def["src_layer_name"],
                                       ", ".join("{:s}({:s})".format(attr_name, missing_attrs[attr_name])
                                                 for attr_name in sorted(missing_attrs.keys()))))
