#!/usr/bin/env python3


import logging
import sys
import time
from argparse import ArgumentParser
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from qc_tool.common import CONFIG
from qc_tool.common import create_job_dir
from qc_tool.worker.jobs import JobIdentifierError
from qc_tool.worker.jobs import normalize_job_uuid
from qc_tool.worker.jobs import validate_path_component


LOG_FORMAT = "{asctime} {name}:{levelname} {pathname}:{lineno} {message}"
LOG_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_FILENAME = "job.log"
MAX_S3_SECRET_BYTES = 4096


log = logging.getLogger(__name__)


def read_s3_secret(stream):
    """Read one bounded UTF-8 secret from the scheduler's private pipe."""
    raw_secret = stream.read(MAX_S3_SECRET_BYTES + 1)
    if not raw_secret:
        raise ValueError("The S3 secret-key pipe was empty.")
    if len(raw_secret) > MAX_S3_SECRET_BYTES:
        raise ValueError("The S3 secret key is too large.")
    try:
        return raw_secret.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("The S3 secret key is not valid UTF-8.") from exc


def init_logging(job_dir, log_filename=LOG_FILENAME):
    formatter = logging.Formatter(fmt=LOG_FORMAT, style="{", datefmt=LOG_TIME_FORMAT)
    # All log timestamps should be in UTC.
    formatter.converter = time.gmtime
    # Every job has its own log located in its job dir.
    handler = logging.FileHandler(job_dir.joinpath(log_filename))
    handler.setFormatter(formatter)


def main():
    # Import the heavy validator stack only in the job process. Keeping module
    # import lightweight also makes credential parsing independently testable.
    from qc_tool.worker.dispatch import dispatch

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
    parser.add_argument(
        "--s3-secret-key-stdin",
        help="Read the S3 secret key from the scheduler's private stdin pipe.",
        dest="s3_secret_key_stdin",
        action="store_true",
    )
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
    try:
        job_uuid = normalize_job_uuid(pargs.job_uuid[0])
        username = validate_path_component(pargs.username[0], 150, "username")
        filename = validate_path_component(pargs.filename[0], 500, "filename")
    except JobIdentifierError as exc:
        parser.error(str(exc))

    if pargs.s3_host is not None:
        if not pargs.s3_secret_key_stdin:
            parser.error("--s3-secret-key-stdin is required with --s3-host")
        try:
            s3_secret_key = read_s3_secret(sys.stdin.buffer)
        except ValueError as exc:
            parser.error(str(exc))
        s3_params={
            "host": pargs.s3_host[0],
            "access_key": pargs.s3_access_key[0],
            "secret_key": s3_secret_key,
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
