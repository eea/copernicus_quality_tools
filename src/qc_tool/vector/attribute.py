#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import re


DESCRIPTION = "Attribute table is composed of prescribed attributes."
IS_SYSTEM = False


def run_check(params, status):
    import osgeo.ogr as ogr

    from qc_tool.vector.helper import do_layers

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

    # Check if the current delivery is excluded from vector checks
    if "skip_vector_checks" in params:
        if params["skip_vector_checks"]:
            status.info("The delivery has been excluded from vector.attribute check because the vector data source does not contain a single object of interest.")
            return

    for layer_def in do_layers(params):
        ds = ogr.Open(str(layer_def["src_filepath"]))
        layer = ds.GetLayerByName(layer_def["src_layer_name"])
        required_attrs = {attr_name.lower(): attr_type_name.lower()
                         for attr_name, attr_type_name in params["required"].items()}
        if "lengths" in params.keys():
            attr_lengths = {attr_name.lower(): attr_len for attr_name, attr_len in params["lengths"].items()}
        else:
            attr_lengths = {}
        ignored_attrs = params["ignored"].copy()
        extra_attrs = {}
        bad_type_attrs = {}
        bad_attr_lengths = {}
        for field_defn in layer.schema:
            field_name = field_defn.name.lower()
            field_type = field_defn.GetType()
            field_length = field_defn.GetWidth()

            if field_name in attr_lengths:
                if field_length <= attr_lengths[field_name]:
                    del attr_lengths[field_name]
                else:
                    bad_attr_lengths.update({field_name: str(field_length)})

            if field_name in ignored_attrs:
                # Ignored attribute.
                ignored_attrs.remove(field_name)

            elif field_name in required_attrs:
                # Required attribute.
                if field_type not in OGR_TYPES:
                    # Attribute type is unknown.
                    bad_type_attrs.update({field_name: "unknown-type"})
                elif field_type not in ALLOWED_TYPES:
                    # Attribute type is not allowed.
                    bad_type_attrs.update({field_name: OGR_TYPES[field_type]})
                elif ALLOWED_TYPES[field_type] != required_attrs[field_name]:
                    # Attribute type does not match the type in product definition.
                    bad_type_attrs.update({field_name: ALLOWED_TYPES[field_type]})
                del required_attrs[field_name]
            else:
                # Extra attribute.
                extra_attrs.update({field_name: OGR_TYPES[field_type]})

        # The attributes remaining in required_attrs are missing.
        if len(required_attrs) > 0:
            status.aborted("Layer {:s} has missing attributes: {:s}."
                           .format(layer_def["src_layer_name"],
                                   ", ".join("{:s}({:s})".format(attr_name, required_attrs[attr_name])
                                             for attr_name in sorted(required_attrs.keys()))))
        if len(extra_attrs) > 0:
            status.failed("Layer {:s} has extra attributes: {:s}."
                          .format(layer_def["src_layer_name"],
                                  ", ".join("{:s}({:s})".format(attr_name, extra_attrs[attr_name])
                                            for attr_name in sorted(extra_attrs.keys()))))
        if len(bad_type_attrs) > 0:
            status.aborted("Layer {:s} has attributes with bad type: {:s}."
                           .format(layer_def["src_layer_name"],
                                   ", ".join("{:s}({:s})".format(attr_name, bad_type_attrs[attr_name])
                                             for attr_name in sorted(bad_type_attrs.keys()))))

        if len(bad_attr_lengths) > 0:
            status.failed("Layer {:s} has attributes with bad length: {:s}."
                          .format(layer_def["src_layer_name"],
                                  ", ".join("{:s}({:s})".format(attr_name, bad_attr_lengths[attr_name])
                                            for attr_name in sorted(bad_attr_lengths.keys()))))
