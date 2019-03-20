#! /usr/bin/env python3
# -*- coding: utf-8 -*-


import json
import socket
from urllib import request
from urllib.error import HTTPError
from urllib.error import URLError
from xml.etree import ElementTree


DESCRIPTION = "Metadata are in accord with INSPIRE specification."
IS_SYSTEM = False


def run_check(params, status):

    from qc_tool.raster.helper import do_raster_layers

    for layer_def in do_raster_layers(params):

        # check existence of xml metadata file .xml or .tif.xml
        xml_filepath1 = layer_def["src_filepath"].with_suffix(".xml")
        xml_filepath2 = layer_def["src_filepath"].with_suffix(".tif.xml")

        if xml_filepath1.exists():
            xml_filepath = xml_filepath1
        elif xml_filepath2.exists():
            xml_filepath = xml_filepath2
        else:
            status.failed("Expected XML metadata file {:s} or {:s} is missing."
                          .format(xml_filepath1.name, xml_filepath2.name))
            continue

        # check if the metadata file is a valid xml document.
        try:
            ElementTree.parse(str(xml_filepath))
        except ElementTree.ParseError:
            status.failed("XML metadata file {:s} is not a valid XML document.".format(xml_filepath.name))
            continue

        METADATA_SERVICE_HOST = 'http://inspire-geoportal.ec.europa.eu'
        METADATA_SERVICE_ENDPOINT = 'GeoportalProxyWebServices/resources/INSPIREResourceTester'

        url = '{}/{}'.format(METADATA_SERVICE_HOST, METADATA_SERVICE_ENDPOINT)
        headers = {'Accept': 'application/json', 'Content-Type': 'text/plain'}
        metadata = xml_filepath.read_text(encoding='utf-8')

        # post the metadata file content to INSPIRE validator API.
        inspire_validator_running = False
        try:
            req = request.Request(url, data=metadata.encode('utf-8'), headers=headers)
            with request.urlopen(req, timeout=60) as resp:
                report_url = resp.headers['Location']
                json_data = json.loads(resp.read().decode('utf-8'))
                inspire_validator_running = True
        except HTTPError:
            status.info("Unable to validate INSPIRE metadata by validator {:s}. "
                        "Internet connection is not accessible."
                        .format(METADATA_SERVICE_HOST))
        except URLError:
            status.info("Unable to validate INSPIRE metadata by validator {:s}. "
                        "Internet connection timeout."
                        .format(METADATA_SERVICE_HOST))
        except socket.timeout:
            status.info("Unable to validate INSPIRE metadata by validator {:s}. "
                        "Internet connection timeout."
                        .format(METADATA_SERVICE_HOST))

        if inspire_validator_running:
            # Completeness_indicator is 100.0 means that INSPIRE validation is OK (even if there are some warnings).
            if "value" not in json_data or json_data["value"] is None:
                inspire_ok = False

            elif "CompletenessIndicator" not in json_data["value"]:
                inspire_ok = False

            elif json_data["value"]["CompletenessIndicator"] is None:
                inspire_ok = False

            elif json_data["value"]["CompletenessIndicator"] != 100:
                inspire_ok = False
            else:
                inspire_ok = True

            if not inspire_ok:
                status.failed("Using INSPIRE validator service {:s}. "
                              "INSPIRE metadata file {:s} is not valid or incomplete. "
                              "See attached report for details."
                              .format(METADATA_SERVICE_HOST, xml_filepath.name))

                # save the attachment to output directory.
                inspire_filename = "s{:02d}_{:s}_metadata_error.json"
                inspire_filename = inspire_filename.format(params["step_nr"], layer_def["src_filepath"].stem)
                inspire_filepath = params["output_dir"].joinpath(inspire_filename)
                inspire_filepath.write_text(json.dumps(json_data, indent=4, sort_keys=True))
                status.add_attachment(inspire_filepath.name)
