#!/usr/bin/env python3


import logging
import time
from argparse import ArgumentParser
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from qc_tool.common import CONFIG
from qc_tool.common import create_job_dir
from qc_tool.worker.dispatch import dispatch


LOG_FORMAT = "{asctime} {name}:{levelname} {pathname}:{lineno} {message}"
LOG_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_FILENAME = "job.log"


log = logging.getLogger(__name__)


def init_logging(job_dir, log_filename=LOG_FILENAME):
    formatter = logging.Formatter(fmt=LOG_FORMAT, style="{", datefmt=LOG_TIME_FORMAT)
    # All log timestamps should be in UTC.
    formatter.converter = time.gmtime
    # Every job has its own log located in its job dir.
    handler = logging.FileHandler(job_dir.joinpath(log_filename))
    handler.setFormatter(formatter)


def main():
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
    parser.add_argument("--s3-host",
                        help="URL of the S3 host where the delivery files can be downloaded from.",
                        dest="s3_host",
                        default=None,
                        action="store",
                        nargs=1,
                        required=False)
    parser.add_argument("--s3-access-key",
                        help="S3 access key.",
                        dest="s3_access_key",
                        default=None,
                        action="store",
                        nargs=1,
                        required=False)
    parser.add_argument("--s3-secret-key",
                        help="S3 secret key.",
                        dest="s3_secret_key",
                        default=None,
                        action="store",
                        nargs=1,
                        required=False)
    parser.add_argument("--s3-bucketname",
                        help="S3 bucket name where the delivery files can be downloaded from.",
                        dest="s3_bucketname",
                        default=None,
                        action="store",
                        nargs=1,
                        required=False)
    parser.add_argument("--s3-key-prefix",
                        help="Prefix of the s3 delivery object (without any file extension)",
                        dest="s3_key_prefix",
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
    job_uuid = pargs.job_uuid[0]
    username = pargs.username[0]
    filename = pargs.filename[0]

    if pargs.s3_host is not None:
        s3_params={
            "host": pargs.s3_host[0],
            "access_key": pargs.s3_access_key[0],
            "secret_key": pargs.s3_secret_key[0],
            "bucketname": pargs.s3_bucketname[0],
            "key_prefix": pargs.s3_key_prefix[0]
        }
    else:
        s3_params = None

    filepath = CONFIG["incoming_dir"].joinpath(username, filename)
    if pargs.skip_steps is None:
        skip_steps = tuple()
    else:
        skip_steps = tuple(int(i) for i in pargs.skip_steps[0].split(","))

    # Create job dir.
    job_dir = create_job_dir(job_uuid)

    # Set up logging.
    init_logging(job_dir)
    log.info("Logging of the job {:s} has been started.".format(job_uuid))

    # Run the checks.
    dispatch(job_uuid, username, filepath, pargs.product_ident[0], skip_steps, s3_params)


if __name__ == "__main__":
    main()
