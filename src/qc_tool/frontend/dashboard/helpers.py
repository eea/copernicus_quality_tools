#!/usr/bin/env python3


import logging
import os
import random
import re
import string
from datetime import datetime
from shutil import copyfile
from shutil import copytree
from pathlib import Path
import boto3

from qc_tool.common import CONFIG
from qc_tool.common import compose_job_dir
from qc_tool.common import get_product_descriptions
from qc_tool.common import JOB_INPUT_DIRNAME
from qc_tool.common import JOB_OUTPUT_DIRNAME
from qc_tool.common import load_job_result
from qc_tool.common import UNKNOWN_REFERENCE_YEAR_LABEL


logger = logging.getLogger(__name__)


def generate_api_key():
    """
    Generates an API key with 25 random characters.
    """
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=25))


def get_announcement_message():
    """
    Reads announcement message from the announcement.txt file.
    """
    try:
        if CONFIG["announcement_path"].is_file():
            return CONFIG["announcement_path"].read_text()
        else:
            return None
    except:
        return None

def get_boundary_version():
    """
    Reads .txt file in boundary/raster folder with format ver_{date}.txt and return datetime string.
    """
    try:
        boundaries_dir = CONFIG["boundary_dir"]
        rasterdir_path = Path(boundaries_dir).joinpath('raster')
        files_in_rasterpath = os.listdir(rasterdir_path)
        for file_name in files_in_rasterpath:
            if 'ver' in file_name:
               version_str = file_name.split('_')[1].split('.')[0]
               datetime_str = datetime.strptime(version_str,"%d%m%Y").strftime("%d/%m/%Y")
               return datetime_str       
    except:    
        return 'None'

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
    Tries to guess the product ident from the uploaded zip file name.
    """
    fn = delivery_filepath.stem.lower()

    product_descriptions = get_product_descriptions()
    for product_ident, product_description in product_descriptions.items():
        if fn.startswith(product_ident) or fn.endswith(product_ident):
            return product_ident
    return None

def find_s3_delivery(host, access_key, secret_key, bucketname, pattern):
    """
    Tries to find the delivery files on S3 storage based on user-defined filename pattern.
    """

    # Check the S3 storage connection, filter objects by naming pattern
    try:
        s3 = boto3.resource('s3', aws_access_key_id=access_key, aws_secret_access_key=secret_key, endpoint_url=host)
        bucket = s3.Bucket(bucketname)
        objects_filtered = list(bucket.objects.filter(Prefix=pattern))
        if len(objects_filtered) == 0:
            return {"delivery_filename": None,
                    "message": "s3-key prefix does not match any object on S3 storage"}
        else:
            s3_deliveries_found = list()
            for obj in objects_filtered:
                delivery_file_prefix = os.path.join(os.path.dirname(obj.key), os.path.basename(obj.key).split(os.extsep)[0])
                s3_deliveries_found.append(delivery_file_prefix)
            delivery_found = list(set(s3_deliveries_found))
            if len(delivery_found) > 1:
                return {"delivery_filename": None,
                        "message": "s3-key prefix does not match the delivery unambiguously"}
            else:
                return {"delivery_filename": delivery_found[0],
                        "message": "s3 delivery found: '{:s}'".format(delivery_found[0])}
    except Exception as e:
        return {"delivery_filename": None,
                "message": str(e)}

def get_s3_delivery_size(host, access_key, secret_key, bucketname, pattern):
    """
    Get the summary size of the S3 delivery objects.
    """
    try:
        s3 = boto3.resource('s3', aws_access_key_id=access_key, aws_secret_access_key=secret_key, endpoint_url=host)
        bucket = s3.Bucket(bucketname)
        objects_filtered = list(bucket.objects.filter(Prefix=pattern))
        if len(objects_filtered) == 0:
            return None
        else:
            s3_dlivery_size = 0
            for obj in objects_filtered:
                s3_dlivery_size += obj.size
            return s3_dlivery_size
    except:
        return None

def submit_job(job_uuid, input_filepath, submission_dir, submission_date, is_s3=False):
    # Prepare parameters.
    job_uuid = str(job_uuid)
    job_result = load_job_result(job_uuid)
    job_dir = compose_job_dir(job_uuid)
    reference_year = job_result.get("reference_year", None)
    if reference_year is None:
        reference_year = UNKNOWN_REFERENCE_YEAR_LABEL
    if not is_s3:
        uploaded_name = re.sub(".zip$", "", job_result["filename"])
    else:
        uploaded_name = job_result["filename"]

    # Create submission directory for the job.
    submission_dirname = "{:s}-{:s}-{:s}.d".format(submission_date.strftime("%Y%m%d"),
                                                   uploaded_name,
                                                   job_uuid)
    job_submission_dir = (submission_dir.joinpath(job_result["product_ident"])
                                        .joinpath(reference_year)
                                        .joinpath(submission_dirname))
    job_submission_dir.mkdir(parents=True, exist_ok=False)

    # Copy all files in job's root directory.
    for src_filepath in job_dir.iterdir():
        if src_filepath.is_file() and not src_filepath.is_symlink():
            dst_filepath = job_submission_dir.joinpath(src_filepath.name)
            copyfile(str(src_filepath), str(dst_filepath))

    # Copy output.d.
    src_filepath = job_dir.joinpath(JOB_OUTPUT_DIRNAME)
    dst_filepath = job_submission_dir.joinpath(src_filepath.name)
    copytree(str(src_filepath), str(dst_filepath))

    # Copy the uploaded file.
    if not is_s3:
        dst_dir = job_submission_dir.joinpath(JOB_INPUT_DIRNAME)
        dst_dir.mkdir()
        dst_filepath = dst_dir.joinpath(input_filepath.name)
        copyfile(str(input_filepath), str(dst_filepath))

    # Put stamp confirming finished submission.
    dst_filepath = job_submission_dir.joinpath("SUBMITTED")
    final_date = datetime.utcnow().isoformat()
    dst_filepath.write_text(final_date)