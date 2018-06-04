#!/usr/bin/env python3


from pathlib import Path

from qc_tool.wps.manager import create_connection_manager
from qc_tool.wps.manager import create_jobdir_manager
from qc_tool.wps.registry import get_check_function

import qc_tool.wps.common_check.dummy
import qc_tool.wps.raster_check.r1
import qc_tool.wps.raster_check.r2
import qc_tool.wps.raster_check.r3
import qc_tool.wps.raster_check.r4
import qc_tool.wps.raster_check.r5
import qc_tool.wps.raster_check.r7
import qc_tool.wps.raster_check.r14
import qc_tool.wps.raster_check.r15
import qc_tool.wps.vector_check.import2pg
import qc_tool.wps.vector_check.v1
import qc_tool.wps.vector_check.v2
import qc_tool.wps.vector_check.v3
import qc_tool.wps.vector_check.v4
import qc_tool.wps.vector_check.v11
from qc_tool.common import load_product_type_definition
from qc_tool.common import load_check_defaults


def dispatch(job_uuid, filepath, product_type_name, optional_check_idents, update_result_func=None):
    # Read configurations.
    check_defaults = load_check_defaults()
    product_type = load_product_type_definition(product_type_name)

    # Prepare check idents.
    product_check_idents = set(check["check_ident"] for check in product_type["checks"])
    optional_check_idents = set(optional_check_idents)

    # Ensure passed optional checks take part in product type.
    incorrect_check_idents = optional_check_idents - product_check_idents
    if len(incorrect_check_idents) > 0:
        raise IncorrectCheckException("Incorrect checks passed, product_type_name={:s}, incorrect_check_idents={:s}.".format(repr(product_type_name), repr(sorted(incorrect_check_idents))))

    # Compile suite of checks to be performed.
    check_suite = [check
                   for check in product_type["checks"]
                   if check["required"] or check["check_ident"] in optional_check_idents]

    # Prepare variable keeping results of all checks.
    suite_result = {}

    # Wrap the job with needful managers.
    with create_connection_manager(job_uuid) as connection_manager, create_jobdir_manager(job_uuid) as jobdir_manager:
        job_params = {}
        job_params["connection_manager"] = connection_manager
        job_params["job_dir"] = str(jobdir_manager.job_dir)

        # Run check suite.
        for check in check_suite:
            # Prepare parameters.
            check_params = {}
            if check["check_ident"] in check_defaults:
                check_params.update(check_defaults[check["check_ident"]])
            if "parameters" in product_type:
                check_params.update(product_type["parameters"])
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

            # Update wps output.
            if update_result_func is not None:
                update_result_func(suite_result)

            # Abort validation if wanted.
            if check_result["status"] == "aborted":
                break

    return suite_result


class IncorrectCheckException(Exception):
    pass
