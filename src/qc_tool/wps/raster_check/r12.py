#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from urllib import request
from urllib.error import HTTPError
from xml.etree import ElementTree


from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):

    # check existence of xml metadata file.
    xml_filepath = params["filepath"].with_suffix(".xml")

    if not xml_filepath.exists():
        status.add_message("Expected XML metadata file {:s} is missing.".format(xml_filepath.name))
        return

    # check if the metadata file is a valid xml document.
    try:
        ElementTree.parse(str(xml_filepath))
    except ElementTree.ParseError:
        status.add_message("XML metadata file {:s} is not a valid XML document.".format(xml_filepath.name))
        return

    METADATA_SERVICE_HOST = 'http://inspire-geoportal.ec.europa.eu'
    METADATA_SERVICE_ENDPOINT = 'GeoportalProxyWebServices/resources/INSPIREResourceTester'

    url = '{}/{}'.format(METADATA_SERVICE_HOST, METADATA_SERVICE_ENDPOINT)
    headers = {'Accept': 'application/json', 'Content-Type': 'text/plain'}
    metadata = xml_filepath.read_text(encoding='utf-8')

    # post the metadata file content to INSPIRE validator API.
    try:
        req = request.Request(url, data=metadata.encode('utf-8'), headers=headers)
        with request.urlopen(req) as resp:
            report_url = resp.headers['Location']
            json_data = json.loads(resp.read().decode('utf-8'))
    except HTTPError:
        status.add_message("Unable to validate INSPIRE metadata. Internet connection is not accessible.")
        return

    # Completeness_indicator is 100.0 means that INSPIRE validation is OK (even if there are some warnings).
    completeness_indicator = json_data['value']['CompletenessIndicator']

    if completeness_indicator != 100:
        status.add_message("INSPIRE metadata is incomplete. See attached report for details."
                           "More details are at URL: {:s}".format(report_url))

        # save the attachment to output directory.
        metadata_report_filepath = params["output_dir"].joinpath(params["filepath"].stem + "_metadata_error.json")
        metadata_report_filepath.write_text(json.dumps(json_data, indent=4, sort_keys=True))
        status.add_attachment(metadata_report_filepath.name)
        return
