#!/usr/bin/env python3


from contextlib import ExitStack
from pathlib import Path

from qc_tool.wps.manager import create_connection_manager
from qc_tool.wps.manager import create_jobdir_manager
from qc_tool.wps.registry import get_check_function

from qc_tool.common import load_check_defaults
from qc_tool.common import load_product_definitions
from qc_tool.common import prepare_empty_status
from qc_tool.common import strip_prefix


def dispatch(job_uuid, filepath, product_ident, optional_check_idents, update_status_func=None):
    optional_check_idents = set(optional_check_idents)

    # Read configurations.
    check_defaults = load_check_defaults()
    product_definitions = load_product_definitions(product_ident)
    defined_checks = [check
                      for product_definition in product_definitions if "checks" in product_definition
                      for check in product_definition["checks"]]

    # Ensure passed optional checks take part in product.
    defined_optional_check_idents = {check["check_ident"] 
                                     for check in defined_checks if not check["required"]}
    incorrect_check_idents = optional_check_idents - defined_optional_check_idents
    if len(incorrect_check_idents) > 0:
        message = "Incorrect checks passed, product_ident={:s}, incorrect_check_idents={:s}.".format(repr(product_ident), repr(sorted(incorrect_check_idents)))
        raise IncorrectCheckException(message)

    # Prepare variable keeping results of all checks.
    required_check_count = len([check for check in defined_checks if check["required"]])
    job_check_count = required_check_count + len(optional_check_idents)
    checks_passed_count = 0

    job_status = prepare_empty_status(product_ident)
    job_status_check_idx = {check["check_ident"]: check for check in job_status["checks"]}

    # Wrap the job with needful managers.
    with ExitStack() as exit_stack:

        job_params = {}
        job_params["connection_manager"] = exit_stack.enter_context(create_connection_manager(job_uuid))
        jobdir_manager = exit_stack.enter_context(create_jobdir_manager(job_uuid))
        job_params["job_dir"] = str(jobdir_manager.job_dir)

        try:
            for product_definition in product_definitions:
                if "checks" in product_definition:
                    for check in product_definition["checks"]:
                        if check["required"] or check["check_ident"] in optional_check_idents:
                            # Update status.
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
                            check_result = func(str(filepath), check_params)

                            # Set the check result into the job status.
                            job_status_check_idx[check["check_ident"]]["status"] = check_result["status"]
                            if "message" in check_result:
                                job_status_check_idx[check["check_ident"]]["message"] = check_result["message"]

                            # Abort validation job.
                            if check_result["status"] == "aborted":
                                raise AbortJob()

                            # Update job params.
                            if "params" in check_result:
                                job_params.update(check_result["params"])

                        else:
                            job_status_check_idx[check["check_ident"]]["status"] = "skipped"

        except AbortJob:
            pass

    return job_status


class AbortJob(Exception):
    pass

class IncorrectCheckException(Exception):
    pass
