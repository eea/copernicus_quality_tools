#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import socket
from urllib import request
from urllib.error import HTTPError
from urllib.error import URLError
from xml.etree import ElementTree

from qc_tool.wps.helper import do_layers
from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):

    # Find all .xml files to check. There is one .xml file per .gdb or .shp
    layer_src_filepaths = set([layer_def["src_filepath"] for layer_def in do_layers(params)])

    for src_filepath in layer_src_filepaths:

        # Check existence of xml metadata file. can be .xml or .shp.xml
        xml_filepath1 = src_filepath.with_suffix(".xml")
        xml_filepath2 = src_filepath.with_suffix(src_filepath.suffix + ".xml")
        xml_filepath3 = src_filepath.parent.joinpath("metadata", src_filepath.stem + ".xml")
        xml_filepath4 = src_filepath.parent.joinpath("metadata", src_filepath.name + ".xml")

        if xml_filepath1.exists():
            xml_filepath = xml_filepath1
        elif xml_filepath2.exists():
            xml_filepath = xml_filepath2
        elif xml_filepath3.exists():
            xml_filepath = xml_filepath3
        elif xml_filepath4.exists():
            xml_filepath = xml_filepath4
        else:
            status.failed("Expected XML metadata file {:s} or {:s} or is missing."
                          .format(xml_filepath1.name, xml_filepath2.name))
            return

        # check if the metadata file is a valid xml document.
        try:
            ElementTree.parse(str(xml_filepath))
        except ElementTree.ParseError:
            status.failed("XML metadata file {:s} is not a valid XML document.".format(xml_filepath.name))
            return

        METADATA_SERVICE_HOST = 'http://inspire-geoportal.ec.europa.eu'
        METADATA_SERVICE_ENDPOINT = 'GeoportalProxyWebServices/resources/INSPIREResourceTester'

        url = '{}/{}'.format(METADATA_SERVICE_HOST, METADATA_SERVICE_ENDPOINT)
        headers = {'Accept': 'application/json', 'Content-Type': 'text/plain'}
        metadata = xml_filepath.read_text(encoding='utf-8')

        # post the metadata file content to INSPIRE validator API.
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
            continue
        except URLError:
            status.info("Unable to validate INSPIRE metadata by validator {:s}. "
                        "Internet connection timeout."
                        .format(METADATA_SERVICE_HOST))
            continue
        except socket.timeout:
            status.info("Unable to validate INSPIRE metadata by validator {:s}. "
                        "Internet connection timeout."
                        .format(METADATA_SERVICE_HOST))
            continue

        # Completeness_indicator is 100.0 means that INSPIRE validation is OK (even if there are some warnings).
        if "value" not in json_data:
            inspire_ok = False

        elif "CompletenessIndicator" not in json_data["value"] or json_data["value"]["CompletenessIndicator"] is None:
            inspire_ok = False

        elif json_data["value"]["CompletenessIndicator"] is None:
            inspire_ok = False

        elif json_data["value"]["CompletenessIndicator"] != 100:
            inspire_ok = False
        else:
            inspire_ok = True

        if not inspire_ok:
            status.failed("INSPIRE metadata is in incorrect format or incomplete. See attached report for details.")

            # save the attachment to output directory.
            metadata_report_filepath = params["output_dir"].joinpath(src_filepath.stem + "_metadata_error.json")
            metadata_report_filepath.write_text(json.dumps(json_data, indent=4, sort_keys=True))
            status.add_attachment(metadata_report_filepath.name)
