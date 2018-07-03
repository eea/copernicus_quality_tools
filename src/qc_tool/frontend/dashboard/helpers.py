import json
import os
import requests
from datetime import datetime
from lxml import etree
from django.utils.dateparse import parse_datetime

#from .models import Job
#from .models import UploadedFile

from qc_tool.common import compose_job_status_filepath
from qc_tool.common import compose_wps_status_filepath
from qc_tool.common import get_all_wps_uuids
from qc_tool.common import get_product_descriptions
from qc_tool.common import load_product_definition
from qc_tool.common import prepare_empty_job_status


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


def guess_product_ident(product_filename):
    """
    Tries to guess the product ident from the uploaded file name
    This should use the file_name_regex in each product's configuration
    :param product_filename:
    :return:
    """
    is_20m_raster = False
    is_100m_raster = False
    is_vector = False

    if "_020m" in product_filename:
        is_20m_raster = True
    if "_100m" in product_filename:
        is_100m_raster = True


    fn = product_filename.lower()

    if fn.startswith("clc"):
        return "clc"
    elif fn.startswith("ua"):
        return "ua"
    elif fn.startswith("fty"):
        if "_020m" in fn:
            return "fty_YYYY_020m"
        else:
            return "fty_YYYY_100m"
    else:
        return None



def update_jobs_db():
    """
    updates the jobs table in the db focusing on recent job runs.
    :return:
    """
    job_infos = []
    for job_uuid in get_all_wps_uuids():
        wps_status_filepath = compose_wps_status_filepath(job_uuid)
        wps_status = wps_status_filepath.read_text()
        job_info = parse_status_document(wps_status)
        job_info["uid"] = job_uuid

        job_status_filepath = compose_job_status_filepath(job_uuid)
        if job_status_filepath.exists() and job_info["status"] == "finished":
            job_status = job_status_filepath.read_text()
            job_status = json.loads(job_status)
            overall_status_ok = all((check["status"] in ("ok", "skipped") for check in job_status["checks"]))
            job_info["overall_result"] = ["FAILED", "PASSED"][overall_status_ok]

        job_infos.append(job_info)

    #for job_info in job_infos:
        #try:
            #db_job = Job.objects.get(job_uuid=job_info["uid"])
        #except:
            #db_job = Job()
            #db_job.job_uuid = job_info["uid"]

    # sort by start_time in descending order
    job_infos = sorted(job_infos, key=lambda ji: ji['start_time'], reverse=True)


def parse_status_document(document_content):
    """
    Parses the status document from the WPS
    :param document_content: the content of the document. This is obtained
    in the statusLocation attribute of the WPS 1.0.0 response
    :return: a status document dictionary with items filepath, product_type_name, start_time, end_time,
             percent_complete, wps_status_location, status, result, log_info

    """

    STATUS_ACCEPTED = 'accepted'
    STATUS_FAILED = 'error'
    STATUS_STARTED = 'started'
    STATUS_SUCCEEDED = 'finished'

    doc = {'uid': None,
           'filepath': None,
           'product_type_name': None,
           'check_idents': None,
           'start_time': None,
           'end_time': None,
           'percent_complete': 0,
           'status': 'failed',
           'result': None,
           'log_info': None,
           'wps_identifier': None,
           'overall_result': None
           }

    ns = {'wps': 'http://www.opengis.net/wps/1.0.0', 'ows': 'http://www.opengis.net/ows/1.1'}

    tree = etree.fromstring(document_content)

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

    # status of the WPS output
    status_tags = tree.xpath('//wps:Status', namespaces=ns)
    if len(status_tags) == 0:
        # this meens there is no status element --- some exception occurred during that request
        doc['status'] = STATUS_FAILED
        doc['overall_result'] = STATUS_FAILED
        return doc

    status_tag = status_tags[0]
    accepted_tags = status_tag.findall('wps:ProcessAccepted', ns)
    started_tags = status_tag.findall('wps:ProcessStarted', ns)
    succeeded_tags = status_tag.findall('wps:ProcessSucceeded', ns)
    error_tags = status_tag.findall('wps:ProcessFailed', ns)

    if len(accepted_tags) > 0:
        doc['status'] = STATUS_ACCEPTED
        doc['start_time'] = parse_datetime(status_tag.attrib['creationTime'])
        doc['log_info'] = accepted_tags[0].text
        doc['result'] = dict()
        doc['result']['unknown'] = {'description': '', 'status': 'accepted', 'message': doc['log_info']}
        accepted_tag = accepted_tags[0]
        doc['log_info'] = accepted_tag.text
        if "percentCompleted" in accepted_tag.attrib:
            doc['percent_complete'] = accepted_tag.attrib["percentCompleted"]
        return doc

    elif len(started_tags) > 0:
        doc['status'] = STATUS_STARTED
        started_tag = started_tags[0]
        doc['log_info'] = started_tag.text
        doc['start_time'] = parse_datetime(status_tag.attrib['creationTime'])
        if "percentCompleted" in started_tag.attrib:
            doc["percent_complete"] = started_tag.attrib["percentCompleted"]
        doc["result"] = dict()
        status = "running {:s}%".format(doc["percent_complete"])
        doc["result"]["unknown"] = {"status": status, "message": doc["log_info"]}

    elif len(succeeded_tags) > 0:
        doc['status'] = STATUS_SUCCEEDED
        doc['log_info'] = succeeded_tags[0].text
        doc['start_time'] = parse_datetime(status_tag.attrib['creationTime'])
        doc['end_time'] = parse_datetime(status_tag.attrib['creationTime'])
        doc['percent_complete'] = "100"

    # wps:ProcessFailed means there was an unhandled exception (error) in the process
    elif len(error_tags) > 0:
        doc['status'] = STATUS_FAILED
        doc['start_time'] = parse_datetime(status_tag.attrib['creationTime'])
        doc['end_time'] = parse_datetime(status_tag.attrib['creationTime'])

        error_tag = error_tags[0]
        exception_tags = error_tag.findall('wps:ExceptionReport', ns)
        exception_tag = exception_tags[0]
        for sub_tag in exception_tag:
            for detail_tag in sub_tag:
                doc['log_info'] = detail_tag.text
        doc['result'] = dict()
        doc['result']['unknown'] = {'status': STATUS_FAILED, 'message': doc['log_info']}
        doc['overall_result'] = 'ERROR'
        return doc

    return doc
