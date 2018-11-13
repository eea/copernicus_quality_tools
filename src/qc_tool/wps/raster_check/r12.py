#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import json
#import urllib3
from pathlib import Path
import requests


from qc_tool.wps.registry import register_check_function


@register_check_function(__name__)
def run_check(params, status):

    # check existence of xml metadata file.
    xml_suffixes = [".xml", ".tif.xml"]
    expected_xml_files = [params["filepath"].with_suffix(ext_opt) for ext_opt in xml_suffixes]
    expected_xml_filenames = [f.name for f in expected_xml_files]

    xml_filepaths = []
    for suffix in xml_suffixes:
        xml_filepath = params["filepath"].with_suffix(suffix)
        if xml_filepath.exists():
            xml_filepaths.append(xml_filepath)

    if len(xml_filepaths) == 0:
        status.add_message("Expected xml metadata file {:s} is missing.".format(" or ".join(expected_xml_filenames)))
        return

    if len(xml_filepaths) > 1:
        found_xml_filenames = [f.name for f in xml_filepaths]
        status.add_message("More than one xml metadata file found: {:s}".format(", ".join(found_xml_filenames)))

    # FIXME before sending to INSPIRE validator, also check if the file is a non-empty and valid XML document.

    METADATA_SERVICE_HOST = 'http://inspire-geoportal.ec.europa.eu'
    METADATA_SERVICE_ENDPOINT = 'GeoportalProxyWebServices/resources/INSPIREResourceTester'

    url = '{}/{}'.format(METADATA_SERVICE_HOST, METADATA_SERVICE_ENDPOINT)

    headers = {'Accept': 'application/json', 'Content-Type': 'text/plain'}

    metadata = xml_filepaths[0].read_text(encoding='utf-8')

    response = requests.post(url, data=metadata.encode('utf-8'), headers=headers)
    report_url = response.headers['Location']
    json_data = response.json()

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
