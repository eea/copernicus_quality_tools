#! /usr/bin/env python3
# -*- coding: utf-8 -*-


DESCRIPTION = "Delivery can be downloaded from S3 storage."
IS_SYSTEM = True

def run_check(params, status):
    # Raster layers are downloaded to the temporary directory.
    from qc_tool.vector.helper import do_s3_download
    s3_local_dir = params["tmp_dir"].joinpath("r_unzip.d") #TODO find better name
    do_s3_download(params["s3"]["host"],
                   params["s3"]["access_key"],
                   params["s3"]["secret_key"],
                   params["s3"]["bucketname"],
                   params["s3"]["key_prefix"],
                   s3_local_dir,
                   status)