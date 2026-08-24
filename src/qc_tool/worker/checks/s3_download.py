"""Materialize a remote delivery before product-specific checks run."""

from qc_tool.worker.s3_delivery import do_s3_download


DESCRIPTION = "Delivery can be downloaded from approved S3 storage."
IS_SYSTEM = True


def run_check(params, status):
    """Download the registered S3 object set into the job's private temp dir."""

    s3 = params["s3"]
    do_s3_download(
        s3["host"],
        s3["access_key"],
        s3["secret_key"],
        s3["bucketname"],
        s3["key_prefix"],
        params["tmp_dir"].joinpath("r_unzip.d"),
        status,
    )
