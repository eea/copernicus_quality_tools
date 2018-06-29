#!/usr/bin/env python3


import hashlib
import json
from contextlib import ExitStack
from datetime import datetime
from functools import partial
from shutil import copyfile

from qc_tool.common import HASH_ALGORITHM
from qc_tool.common import HASH_BUFFER_SIZE
from qc_tool.common import compose_job_status_filepath
from qc_tool.common import load_check_defaults
from qc_tool.common import load_product_definition
from qc_tool.common import prepare_empty_job_status
from qc_tool.common import strip_prefix
from qc_tool.wps.manager import create_connection_manager
from qc_tool.wps.manager import create_jobdir_manager
from qc_tool.wps.registry import get_check_function


def dispatch(job_uuid, filepath, product_ident, optional_check_idents, update_status_func=None):
    optional_check_idents = set(optional_check_idents)

    # Read configurations.
    check_defaults = load_check_defaults()
    product_definition = load_product_definition(product_ident)

    # Ensure passed optional checks take part in product.
    defined_optional_check_idents = {check["check_ident"]
                                     for check in product_definition["checks"] if not check["required"]}
    incorrect_check_idents = optional_check_idents - defined_optional_check_idents
    if len(incorrect_check_idents) > 0:
        message = "Incorrect checks passed, product_ident={:s}, incorrect_check_idents={:s}.".format(repr(product_ident), repr(sorted(incorrect_check_idents)))
        raise IncorrectCheckException(message)

    # Prepare variable keeping results of all checks.
    job_check_count = len(product_definition["checks"]) - len(defined_optional_check_idents) + len(optional_check_idents)
    checks_passed_count = 0

    job_status = prepare_empty_job_status(product_ident)
    job_status["job_start_date"] = datetime.utcnow().strftime("%Y-%m-%D %H:%M:%S")
    job_status["filename"] = filepath.name
    job_status["job_uuid"] = job_uuid
    job_status_check_idx = {check["check_ident"]: check for check in job_status["checks"]}

    # Wrap the job with needful managers.
    with ExitStack() as exit_stack:

        # Prepare initial job params.
        job_params = {}
        job_params["connection_manager"] = exit_stack.enter_context(create_connection_manager(job_uuid))
        jobdir_manager = exit_stack.enter_context(create_jobdir_manager(job_uuid))
        job_params["tmp_dir"] = jobdir_manager.tmp_dir
        job_params["output_dir"] = jobdir_manager.output_dir

        # Write initial status.json.
        status_filepath = compose_job_status_filepath(job_uuid)
        status_filepath.write_text(json.dumps(job_status))

        # Copy file to be checked into input dir.
        src_filepath = filepath
        dst_filepath = job_params["tmp_dir"].joinpath(filepath.name)
        copyfile(str(src_filepath), str(dst_filepath))
        job_params["filepath"] = dst_filepath

        # Make signature.
        h = hashlib.new(HASH_ALGORITHM)
        with open(str(dst_filepath), "rb") as dst_file:
            for buf in iter(partial(dst_file.read, HASH_BUFFER_SIZE), b''):
                h.update(buf)
        del buf
        job_status["hash"] = h.hexdigest()
        del h

        for check in product_definition["checks"]:

            # Update status.json.
            status_filepath.write_text(json.dumps(job_status))

            if check["required"] or check["check_ident"] in optional_check_idents:
                # Update status at wps
                if update_status_func is not None:
                    percent_done = checks_passed_count / job_check_count * 100
                    update_status_func(check["check_ident"], percent_done)
                checks_passed_count += 1

                # Prepare parameters.
                check_params = {}
                check_params.update(check_defaults["globals"])
                short_check_ident = strip_prefix(check["check_ident"])
                if short_check_ident in check_defaults["checks"]:
                    check_params.update(check_defaults["checks"][short_check_ident])
                if "parameters" in product_definition:
                    check_params.update(product_definition["parameters"])
                if "parameters" in check:
                    check_params.update(check["parameters"])
                check_params.update(job_params)

                # Run the check.
                func = get_check_function(check["check_ident"])
                # FIXME: currently check functions use os.path for path manipulation
                #        while upper server stack uses pathlib.
                #        it is encouraged to choose one or another.
                check_result = func(check_params)

                # Set the check result into the job status.
                job_status_check_idx[check["check_ident"]]["status"] = check_result["status"]
                if "message" in check_result:
                    job_status_check_idx[check["check_ident"]]["message"] = check_result["message"]

                # Abort validation job.
                if check_result["status"] == "aborted":
                    break

                # Update job params.
                if "params" in check_result:
                    job_params.update(check_result["params"])

            else:
                job_status_check_idx[check["check_ident"]]["status"] = "skipped"

        # Update status.json finally.
        status_filepath.write_text(json.dumps(job_status))

    return job_status


class IncorrectCheckException(Exception):
    pass
