"""Copy and verify the exact local ZIP authorized by successful QC."""

import re

from qc_tool.common import JOB_INPUT_DIRNAME
from qc_tool.frontend.dashboard.services.uploads import (
    resolve_user_delivery_upload,
)

from ..errors import PublicationError
from .secure_copy import copy_regular_file


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def copy_delivery_input(
    reserved,
    destination,
    *,
    media_root,
    file_inventory,
):
    expected = reserved.expected_input_digest.casefold()
    if reserved.is_s3:
        if expected and not _SHA256_RE.fullmatch(expected):
            raise PublicationError(
                "invalid_input_digest",
                "The QC job reported an invalid delivery checksum.",
                409,
            )
        raise PublicationError(
            "s3_input_not_archived",
            "Final submission requires a retained copy of the verified input. "
            "S3 source objects are not archived by this publication workflow; "
            "upload the delivery ZIP and run QC before submitting it.",
            409,
        )

    input_path = resolve_user_delivery_upload(
        reserved.filename,
        media_root=media_root,
        username=reserved.username,
    )
    input_directory = destination / JOB_INPUT_DIRNAME
    input_directory.mkdir(mode=0o750)
    digest, size = copy_regular_file(
        input_path,
        input_directory / input_path.name,
    )
    if expected and expected != digest:
        raise PublicationError(
            "input_digest_mismatch",
            "The uploaded ZIP no longer matches the file checked by QC.",
            409,
        )
    file_inventory.append(
        {
            "path": "{}/{}".format(JOB_INPUT_DIRNAME, input_path.name),
            "sha256": digest,
            "size": size,
        }
    )
    return digest
