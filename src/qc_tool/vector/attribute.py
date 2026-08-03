#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import re

DESCRIPTION = "Attribute table is composed of prescribed attributes."
IS_SYSTEM = False


def run_check(params, status):
    import osgeo.ogr as ogr
    from qc_tool.vector.helper import do_layers

    OGR_TYPES = {
        ogr.OFTBinary: "binary",
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
        ogr.OFTWideStringList: "list-of-wide-string"
    }

    ALLOWED_TYPES = {
        ogr.OFTInteger: "integer",
        ogr.OFTInteger64: "integer",
        ogr.OFTReal: "real",
        ogr.OFTString: "string",
        ogr.OFTWideString: "string"
    }

    if params.get("allow_datetime_datatype"):
        ALLOWED_TYPES[ogr.OFTDateTime] = "datetime"

    if params.get("continue_on_error"):
        continue_on_error = True
    else:
        continue_on_error = False

    # Check if the current delivery is excluded from vector checks
    if params.get("skip_vector_checks"):
        status.info("The delivery has been excluded from vector.attribute check because the vector data source does not contain a single object of interest.")
        return

    aborted_messages = []
    failed_messages = []

    for layer_def in do_layers(params):
        ds = ogr.Open(str(layer_def["src_filepath"]))
        layer = ds.GetLayerByName(layer_def["src_layer_name"])
        
        required_attrs = {attr_name.lower(): attr_type_name.lower()
                          for attr_name, attr_type_name in params.get("required", {}).items()}
        
        # Reset expected attribute lengths PER LAYER iteration
        attr_lengths = {attr_name.lower(): attr_len 
                        for attr_name, attr_len in params.get("lengths", {}).items()}
        
        ignored_attrs = params.get("ignored", []).copy()
        extra_attrs = {}
        bad_type_attrs = {}
        bad_attr_lengths = {}

        # Handle the FID column (e.g. "fid" in GPKG) which is not part of layer.schema.
        fid_column_name = layer.GetFIDColumn()
        if fid_column_name:
            fid_col_lower = fid_column_name.lower()
            if fid_col_lower in ignored_attrs:
                ignored_attrs.remove(fid_col_lower)
            elif fid_col_lower in required_attrs:
                if required_attrs[fid_col_lower] == "integer":
                    del required_attrs[fid_col_lower]
                else:
                    bad_type_attrs[fid_col_lower] = "integer"

        for field_defn in layer.schema:
            field_name = field_defn.name.lower()
            field_type = field_defn.GetType()
            field_length = field_defn.GetWidth()

            # Fix length check: do not modify attr_lengths during loop iteration
            if field_name in attr_lengths:
                if field_length > attr_lengths[field_name]:
                    bad_attr_lengths[field_name] = str(field_length)

            if field_name in ignored_attrs:
                ignored_attrs.remove(field_name)

            elif field_name in required_attrs:
                if field_type not in OGR_TYPES:
                    bad_type_attrs[field_name] = "unknown-type"
                elif field_type not in ALLOWED_TYPES:
                    bad_type_attrs[field_name] = OGR_TYPES[field_type]
                elif ALLOWED_TYPES[field_type] != required_attrs[field_name]:
                    bad_type_attrs[field_name] = ALLOWED_TYPES[field_type]
                del required_attrs[field_name]
            else:
                extra_attrs[field_name] = OGR_TYPES.get(field_type, "unknown-type")

        # Accumulate layer-specific messages
        if required_attrs:
            aborted_messages.append(
                "Layer {:s} has missing attributes: {:s}."
                .format(layer_def["src_layer_name"],
                        ", ".join("{:s}({:s})".format(k, required_attrs[k]) for k in sorted(required_attrs.keys())))
            )
        if extra_attrs:
            failed_messages.append(
                "Layer {:s} has extra attributes: {:s}."
                .format(layer_def["src_layer_name"],
                        ", ".join("{:s}({:s})".format(k, extra_attrs[k]) for k in sorted(extra_attrs.keys())))
            )
        if bad_type_attrs:
            aborted_messages.append(
                "Layer {:s} has attributes with bad type: {:s}."
                .format(layer_def["src_layer_name"],
                        ", ".join("{:s}({:s})".format(k, bad_type_attrs[k]) for k in sorted(bad_type_attrs.keys())))
            )
        if bad_attr_lengths:
            failed_messages.append(
                "Layer {:s} has attributes with bad length: {:s}."
                .format(layer_def["src_layer_name"],
                        ", ".join("{:s}({:s})".format(k, bad_attr_lengths[k]) for k in sorted(bad_attr_lengths.keys())))
            )

    # Combined reporting after checking all layers and messages
    all_errors = aborted_messages + failed_messages
    if aborted_messages:
        if continue_on_error:
            status.failed("The following attribute table errors were found:\n{:s}".format("\n".join(all_errors)))
        else:
            status.aborted("The following attribute table errors were found:\n{:s}".format("\n".join(all_errors)))
    elif failed_messages:
        status.failed("The following attribute table errors were found:\n{:s}".format("\n".join(failed_messages)))