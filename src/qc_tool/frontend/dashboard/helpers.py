import json
import os
import requests
from lxml import etree
from django.utils.dateparse import parse_datetime


def get_file_or_dir_size(file_or_dir):
    """
    finds total size of a file or a directory in Bytes
    :param file_or_dir: the full path to the file or directory
    :return:
    """
    if os.path.isfile(file_or_dir):
        return os.path.getsize(file_or_dir)
    else:
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(file_or_dir):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                total_size += os.path.getsize(fp)
        return total_size


def parse_status_document(document_url):
    """
    Parses the status document from the WPS
    :param document_url: the URL of the document. This is obtained
    in the statusLocation attribute of the WPS 1.0.0 response
    :return: a status document dictionary with items filepath, product_type_name, start_time, end_time,
             percent_complete, wps_status_location, status, result, log_info

    """

    STATUS_ACCEPTED = 'accepted'
    STATUS_ERROR = 'error'
    STATUS_FAILED = 'failed'
    STATUS_STARTED = 'started'
    STATUS_SUCCEEDED = 'succeeded'

    uid = document_url.split('/')[-1].split('.')[0]
    doc = {'uid': uid,
           'filepath': None,
           'product_type_name': None,
           'check_idents': None,
           'start_time': None,
           'end_time': None,
           'percent_complete': 0,
           'wps_status_location': document_url,
           'status': 'failed',
           'result': None,
           'log_info': None,
           'wps_identifier': None,
           'overall_result': None
           }

    ns = {'wps': 'http://www.opengis.net/wps/1.0.0', 'ows': 'http://www.opengis.net/ows/1.1'}

    resp = requests.get(document_url)
    tree = etree.fromstring(resp.content)

    identifier_tags = tree.xpath('//wps:Process/ows:Identifier', namespaces=ns)
    if len(identifier_tags) == 0:
        # a process without an identifier is not valid!
        return None
    else:
        identifier_tag = identifier_tags[0].text
        if identifier_tag == 'run_checks':
            # we are only interested in the process named run_check
            doc['wps_identifier'] = 'run_checks'
        else:
            return None

    # data inputs
    input_tags = tree.xpath('//wps:DataInputs/wps:Input', namespaces=ns)
    for input_tag in input_tags:
        ident = input_tag.xpath('ows:Identifier', namespaces=ns)[0].text
        val = input_tag.xpath('wps:Data/wps:LiteralData', namespaces=ns)[0].text

        if ident == 'filepath':
            # print('filepath: {0}'.format(val))
            doc['filepath'] = val

        if ident == 'product_type_name':
            doc['product_type_name'] = val

        if ident == 'optional_check_idents':
            doc['check_idents'] = val

    # data outputs if they exist
    output_tags = tree.xpath('//wps:ProcessOutputs/wps:Output', namespaces=ns)
    for output_tag in output_tags:
        ident = output_tag.xpath('ows:Identifier', namespaces=ns)[0].text

        if ident == 'result':
            out_val = output_tag.xpath('wps:Data/wps:LiteralData', namespaces=ns)
            if len(out_val) > 0:
                out_text = out_val[0].text
                try:
                    out_dict = json.loads(out_text)
                    doc['result'] = out_dict
                    overall_result = 'FAILED'
                    for key, val in out_dict.items():
                        if 'status' in val and val['status'] == 'ok':
                            overall_result = 'PASSED'
                        else:
                            overall_result = 'FAILED'
                            break

                    doc['overall_result'] = overall_result

                except json.JSONDecodeError:
                    # when the output is not in valid JSON format
                    doc['result'] = out_text

    # status of the WPS output
    status_tags = tree.xpath('//wps:Status', namespaces=ns)
    if len(status_tags) == 0:
        # this meens there is no status element --- some exception occurred during that request
        doc['status'] = STATUS_ERROR
        return doc

    status_tag = status_tags[0]
    accepted_tags = status_tag.findall('wps:ProcessAccepted', ns)
    started_tags = status_tag.findall('wps:ProcessStarted', ns)
    succeeded_tags = status_tag.findall('wps:ProcessSucceeded', ns)
    failed_tags = status_tag.findall('wps:ProcessFailed', ns)

    if len(accepted_tags) > 0:
        doc['status'] = STATUS_ACCEPTED
        doc['start_time'] = parse_datetime(status_tag.attrib['creationTime'])
        doc['log_info'] = accepted_tags[0].text
        return doc

    if len(started_tags) > 0:
        doc['status'] = STATUS_STARTED
        started_tag = started_tags[0]
        doc['log_info'] = started_tag.text
        if "percentCompleted" in started_tag.attrib:
            doc['percent_complete'] = started_tag.attrib["percentCompleted"]
        return doc

    if len(succeeded_tags) > 0:
        doc['status'] = STATUS_SUCCEEDED
        doc['log_info'] = succeeded_tags[0].text
        doc['start_time'] = parse_datetime(status_tag.attrib['creationTime'])
        doc['end_time'] = parse_datetime(status_tag.attrib['creationTime'])
        doc['percent_complete'] = "100"
        return doc

    if len(failed_tags) > 0:
        doc['status'] = STATUS_FAILED
        doc['start_time'] = parse_datetime(status_tag.attrib['creationTime'])
        doc['end_time'] = parse_datetime(status_tag.attrib['creationTime'])

        failed_tag = failed_tags[0]
        exception_tags = failed_tag.findall('wps:ExceptionReport', ns)
        exception_tag = exception_tags[0]
        for sub_tag in exception_tag:
            for detail_tag in sub_tag:
                doc['log_info'] = detail_tag.text
        return doc
