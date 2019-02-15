#!/usr/bin/env python3


import json
import logging
import re
from datetime import datetime
from shutil import copyfile
from shutil import copytree
from zipfile import ZipFile

from django.utils.dateparse import parse_datetime
from lxml import etree

from qc_tool.common import compose_job_dir
from qc_tool.common import compose_job_result_filepath
from qc_tool.common import get_product_descriptions
from qc_tool.common import JOB_INPUT_DIRNAME
from qc_tool.common import JOB_OUTPUT_DIRNAME
from qc_tool.common import UNKNOWN_REFERENCE_YEAR_LABEL

from qc_tool.frontend.dashboard import statuses

logger = logging.getLogger(__name__)

def format_date_utc(db_date):
    """
    Formats a DateTime or Timezone object to UTC
    :param db_date:
    :return:
    """
    if db_date is None:
        return None
    else:
        return db_date.strftime('%Y-%m-%dT%H:%M:%S.000Z')


def find_product_description(product_ident):
    """
    given a product ident, retrieve the product description.
    :param product_ident: the product identifier, for example clc, rpz, ua.
    :return: the product description string.
    """
    description = "Unknown"
    product_descriptions = get_product_descriptions()
    if product_ident in product_descriptions:
        description = product_descriptions[product_ident]
    return description


def guess_product_ident(delivery_filepath):
    """
    Tries to guess the product ident from the uploaded file name.
    This should use the file_name_regex in each product's definition.
    """
    is_20m_raster = False
    is_100m_raster = False
    prod_abbrev = "abc"

    fn = delivery_filepath.name.lower()
    if len(fn) > 3:
        prod_abbrev = fn[0:3]

    if "_020m" in fn:
        is_20m_raster = True
    if "_100m" in fn:
        is_100m_raster = True

    if prod_abbrev in ("fty", "gra", "waw", "imc", "imd", "tcd"):
        if is_20m_raster:
            return prod_abbrev + "_020m"
        if is_100m_raster:
            return prod_abbrev + "_100m"

    elif fn.startswith("clc2012"):
        return "clc_2012"
    elif fn.startswith("rpz"):
        return "rpz"
    elif re.match(r"[a-z]{2}[0-9]{3}l[0-9]_[a-z]+", fn):
        logger.debug("Delivery is likely to be urban atlas ...")

        # urban atlas product guessing from name
        logger.debug(delivery_filepath)
        if delivery_filepath.exists():
            with ZipFile(str(delivery_filepath), 'r') as myzip:
                namelist = myzip.namelist()
                for name in namelist:
                    logger.debug(name)
                    if name.endswith(".shp") and "ua2012" in name.lower():
                        return "ua_2012_shp_wo_revised"
                    elif ".gdb" in name:
                        return "ua_2012_gdb"
            return None


def parse_wps_status_document(document_content):
    """
    Parses the status document from the WPS
    :param document_content: the content of the document. This is obtained
    in the statusLocation attribute of the WPS 1.0.0 response
    :return: a status document dictionary with items:
             [filepath, product_type_name, start_time, end_time,
              percent_complete, wps_status_location, status, result, log_info]

    """

    doc = {'uuid': None,
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
            doc['filepath'] = val

        if ident == 'product_type_name':
            doc['product_type_name'] = val

        if ident == 'optional_check_idents':
            doc['check_idents'] = val

    # status of the WPS output
    status_tags = tree.xpath('//wps:Status', namespaces=ns)
    if len(status_tags) == 0:
        # this meens there is no status element --- some exception occurred during that request
        doc['status'] = statuses.WPS_FAILED
        doc['overall_result'] = statuses.WPS_FAILED
        return doc

    status_tag = status_tags[0]
    accepted_tags = status_tag.findall('wps:ProcessAccepted', ns)
    started_tags = status_tag.findall('wps:ProcessStarted', ns)
    succeeded_tags = status_tag.findall('wps:ProcessSucceeded', ns)
    error_tags = status_tag.findall('wps:ProcessFailed', ns)

    if len(accepted_tags) > 0:
        doc['status'] = statuses.WPS_ACCEPTED
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
        doc['status'] = statuses.WPS_STARTED
        started_tag = started_tags[0]
        doc['log_info'] = started_tag.text
        doc['start_time'] = parse_datetime(status_tag.attrib['creationTime'])
        if "percentCompleted" in started_tag.attrib:
            doc["percent_complete"] = started_tag.attrib["percentCompleted"]
        doc["result"] = dict()
        status = "running {:s}%".format(doc["percent_complete"])
        doc["result"]["unknown"] = {"status": status, "message": doc["log_info"]}

    elif len(succeeded_tags) > 0:
        doc['status'] = statuses.WPS_SUCCEEDED
        doc['log_info'] = succeeded_tags[0].text
        doc['start_time'] = parse_datetime(status_tag.attrib['creationTime'])
        doc['end_time'] = parse_datetime(status_tag.attrib['creationTime'])
        doc['percent_complete'] = "100"

    # wps:ProcessFailed means there was an unhandled exception (error) in the process
    elif len(error_tags) > 0:
        doc['status'] = statuses.WPS_FAILED
        doc['start_time'] = parse_datetime(status_tag.attrib['creationTime'])
        doc['end_time'] = parse_datetime(status_tag.attrib['creationTime'])

        error_tag = error_tags[0]
        exception_tags = error_tag.findall('wps:ExceptionReport', ns)
        exception_tag = exception_tags[0]
        for sub_tag in exception_tag:
            for detail_tag in sub_tag:
                doc['log_info'] = detail_tag.text
        doc['result'] = dict()
        doc['result']['unknown'] = {'status': statuses.WPS_FAILED, 'message': doc['log_info']}
        doc['overall_result'] = statuses.WPS_FAILED
        return doc

    return doc

def submit_job(job_uuid, input_filepath, submission_dir, submission_date):
    # Load job result.
    job_result_filepath = compose_job_result_filepath(job_uuid)
    job_result = job_result_filepath.read_text()
    job_result = json.loads(job_result)

    # Prepare parameters.
    job_dir = compose_job_dir(job_uuid)
    reference_year = job_result["reference_year"]
    if reference_year is None:
        reference_year = UNKNOWN_REFERENCE_YEAR_LABEL
    uploaded_name = re.sub(".zip$", "", job_result["filename"])

    # Create submission directory for the job.
    submission_dirname = "{:s}-{:s}-{:s}.d".format(submission_date.strftime("%Y%m%d"),
                                                   uploaded_name,
                                                   job_uuid)
    job_submission_dir = (submission_dir.joinpath(job_result["product_ident"])
                                        .joinpath(reference_year)
                                        .joinpath(submission_dirname))
    job_submission_dir.mkdir(parents=True, exist_ok=False)

    # Copy job result.
    dst_filepath = job_submission_dir.joinpath(src_filepath.name)
    copyfile(str(job_result_filepath), str(dst_filepath))

    # Copy output.d.
    src_filepath = job_dir.joinpath(JOB_OUTPUT_DIRNAME)
    dst_filepath = job_submission_dir.joinpath(src_filepath.name)
    copytree(str(src_filepath), str(dst_filepath))

    # Copy the uploaded file.
    dst_dir = job_submission_dir.joinpath(JOB_INPUT_DIRNAME)
    dst_dir.mkdir()
    dst_filepath = dst_dir.joinpath(input_filepath.name)
    copyfile(str(input_filepath), str(dst_filepath))

    # Put stamp confirming finished submission.
    dst_filepath = job_submission_dir.joinpath("SUBMITTED")
    final_date = datetime.utcnow().isoformat()
    dst_filepath.write_text(final_date)
