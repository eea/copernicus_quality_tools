#!/usr/bin/env python3


from pathlib import Path

from qc_tool.wps.manager import create_connection_manager
from qc_tool.wps.manager import create_jobdir_manager
from qc_tool.wps.registry import get_check_function

from qc_tool.common import load_check_defaults
from qc_tool.common import load_product_definition


def dispatch(job_uuid, filepath, product_name, optional_check_idents, update_status_func=None):
    # Read configurations.
    check_defaults = load_check_defaults()
    product_definition = load_product_definition(product_name)

    # Prepare check idents.
    product_check_idents = set(check["check_ident"] for check in product_definition["checks"])
    optional_check_idents = set(optional_check_idents)

    # Ensure passed optional checks take part in product type.
    incorrect_check_idents = optional_check_idents - product_check_idents
    if len(incorrect_check_idents) > 0:
        raise IncorrectCheckException("Incorrect checks passed, product_name={:s}, incorrect_check_idents={:s}.".format(repr(product_name), repr(sorted(incorrect_check_idents))))

    # Compile suite of checks to be performed.
    check_suite = [check
                   for check in product_definition["checks"]
                   if check["required"] or check["check_ident"] in optional_check_idents]

    # Prepare variable keeping results of all checks.
    suite_result = {}

    # Wrap the job with needful managers.
    with create_connection_manager(job_uuid) as connection_manager, create_jobdir_manager(job_uuid) as jobdir_manager:
        job_params = {}
        job_params["connection_manager"] = connection_manager
        job_params["job_dir"] = str(jobdir_manager.job_dir)

        # Run check suite.
        for i, check in enumerate(check_suite):

            # Update status.
            if update_status_func is not None:
                percent_done = i / len(check_suite) * 100
                update_status_func(check["check_ident"], percent_done)

            # Prepare parameters.
            check_params = {}
            check_params.update(check_defaults["globals"])
            if check["check_ident"] in check_defaults["checks"]:
                check_params.update(check_defaults["checks"][check["check_ident"]])
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

            # Add result to suite results.
            suite_result[check["check_ident"]] = {}
            suite_result[check["check_ident"]]["status"] = check_result["status"]
            if "message" in check_result:
                suite_result[check["check_ident"]]["message"] = check_result["message"]
            if "params" in check_result:
                job_params.update(check_result["params"])

            # Abort validation if wanted.
            if check_result["status"] == "aborted":
                break

    return suite_result


class IncorrectCheckException(Exception):
    pass
