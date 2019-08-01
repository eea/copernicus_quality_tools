#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import json
import socket
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.request import Request
from urllib.request import urlopen
from xml.etree import ElementTree


DESCRIPTION = "Metadata are in accord with INSPIRE specification."
IS_SYSTEM = False

INSPIRE_SERVICE_URL = "http://inspire-geoportal.ec.europa.eu/GeoportalProxyWebServices/resources/INSPIREResourceTester"


def run_check(params, status):
    from qc_tool.vector.helper import do_layers

    for layer_def in do_layers(params):
        # Find the xml metadata file, it can be .xml or .shp.xml.
        for xml_filepath in [layer_def["src_filepath"].parent.joinpath(layer_def["src_filepath"].stem + ".xml"),
                             layer_def["src_filepath"].parent.joinpath(layer_def["src_filepath"].name + ".xml"),
                             layer_def["src_filepath"].parent.joinpath("metadata", layer_def["src_filepath"].stem + ".xml"),
                             layer_def["src_filepath"].parent.joinpath("metadata", layer_def["src_filepath"].name + ".xml")]:
            if xml_filepath.exists():
                break
        else:
            status.failed("Metadata file for {:s} has not been found.".format(layer_def["src_filepath"].name))
            continue

        # Check if the metadata file is a valid xml document.
        try:
            ElementTree.parse(str(xml_filepath))
        except ElementTree.ParseError:
            status.failed("Metadata file {:s} is not a valid XML document.".format(xml_filepath.name))
            continue

        # Post the metadata file content to INSPIRE validator service.
        try:
            req = Request(INSPIRE_SERVICE_URL,
                          data=xml_filepath.read_bytes(),
                          headers={"Accept": "application/json", "Content-Type": "text/plain"})
            with urlopen(req, timeout=60) as resp:
                json_data = json.loads(resp.read().decode("utf-8"))
        except HTTPError as ex:
            status.cancelled("Unable to validate metadata of {:s}: {:s}."
                             .format(xml_filepath.name, str(ex)))
            continue
        except URLError:
            status.cancelled("Unable to validate metadata of {:s}: Service not available."
                             .format(xml_filepath.name))
            continue
        except socket.timeout:
            status.cancelled("Unable to validate metadata of {:s}: Connection timeout."
                             .format(xml_filepath.name))
            continue
        except Exception as ex:
            status.cancelled("Unable to validate metadata of {:s}: {:s}"
                             .format(xml_filepath.name, repr(ex)))
            continue

        # The metadata content is valid if the completeness indicator is equal to 100.0.
        # Warnings are ignored.
        try:
            inspire_ok = json_data["value"]["CompletenessIndicator"] == 100
        except:
            inspire_ok = False

        if not inspire_ok:
            status.failed("Metadata file {:s} is not valid.".format(xml_filepath.name))
            error_filename = "s{:02d}_{:s}_metadata_error.json".format(params["step_nr"], layer_def["src_filepath"].stem)
            error_filepath = params["output_dir"].joinpath(error_filename)
            error_filepath.write_text(json.dumps(json_data, indent=4, sort_keys=True))
            status.add_attachment(error_filepath.name)
