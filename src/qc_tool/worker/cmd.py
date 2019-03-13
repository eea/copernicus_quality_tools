#!/usr/bin/env python3


import logging
from argparse import ArgumentParser
from pathlib import Path

from qc_tool.common import CONFIG
from qc_tool.worker.dispatch import dispatch


log = logging.getLogger(__name__)


def main():
    # Set up logging.
    log.setLevel(logging.DEBUG)
    log.addHandler(logging.StreamHandler())

    # Parse command line arguments.
    parser = ArgumentParser()
    parser.add_argument("--job-uuid",
                        help="The identifier of the job being run.",
                        dest="job_uuid",
                        action="store",
                        nargs=1,
                        required=True)
    parser.add_argument("--product",
                        help="Identifier of the product.",
                        dest="product_ident",
                        action="store",
                        nargs=1,
                        required=True)
    parser.add_argument("--skip-steps",
                        help="Comma separated ordinal numbers of job steps to be skipped.",
                        dest="skip_steps",
                        default=None,
                        action="store",
                        nargs=1,
                        required=False)
    parser.add_argument("username",
                        help="The name of the user managing the delivery.",
                        action="store",
                        nargs=1)
    parser.add_argument("filename",
                        help="Path to delivery file relative to INCOMING_DIR.",
                        action="store",
                        nargs=1)
    pargs = parser.parse_args()

    # Run the job steps.
    username = pargs.username[0]
    filename = pargs.filename[0]
    filepath = CONFIG["incoming_dir"].joinpath(username, filename)
    if pargs.skip_steps is None:
        skip_steps = tuple()
    else:
        skip_steps = tuple(int(i) for i in pargs.skip_steps[0].split(","))
    dispatch(pargs.job_uuid[0], username, filepath, pargs.product_ident[0], skip_steps)


if __name__ == "__main__":
    main()
