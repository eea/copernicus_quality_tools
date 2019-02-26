#!/usr/bin/env python3


import logging
import re
from datetime import datetime
from shutil import copyfile
from shutil import copytree
from zipfile import ZipFile

from qc_tool.common import compose_job_dir
from qc_tool.common import get_product_descriptions
from qc_tool.common import JOB_INPUT_DIRNAME
from qc_tool.common import JOB_OUTPUT_DIRNAME
from qc_tool.common import load_job_result
from qc_tool.common import UNKNOWN_REFERENCE_YEAR_LABEL


logger = logging.getLogger(__name__)


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


def submit_job(job_uuid, input_filepath, submission_dir, submission_date):
    # Prepare parameters.
    job_result = load_job_result(job_uuid)
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
    dst_dir = job_submission_dir.joinpath(JOB_INPUT_DIRNAME)
    dst_dir.mkdir()
    dst_filepath = dst_dir.joinpath(input_filepath.name)
    copyfile(str(input_filepath), str(dst_filepath))

    # Put stamp confirming finished submission.
    dst_filepath = job_submission_dir.joinpath("SUBMITTED")
    final_date = datetime.utcnow().isoformat()
    dst_filepath.write_text(final_date)
