"""Bounded, no-follow loading of the worker result metadata document."""

import json

from qc_tool.common import compose_job_dir
from qc_tool.common import JOB_RESULT_FILENAME
from qc_tool.frontend.dashboard.services.artifacts import ArtifactUnavailable
from qc_tool.frontend.dashboard.services.artifacts import open_regular_artifact

from .errors import ProductUnitResultUnavailable


MAX_PRODUCT_UNIT_RESULT_BYTES = 16 * 1024 * 1024


def load_product_unit_result_document(
    job_uuid,
    *,
    maximum_bytes=MAX_PRODUCT_UNIT_RESULT_BYTES,
):
    """Return one bounded JSON object from a regular result artifact."""

    if (
        isinstance(maximum_bytes, bool)
        or not isinstance(maximum_bytes, int)
        or maximum_bytes <= 0
    ):
        raise ValueError("maximum_bytes must be a positive integer")

    try:
        with open_regular_artifact(
            compose_job_dir(str(job_uuid)),
            JOB_RESULT_FILENAME,
        ) as artifact:
            payload = artifact.read(maximum_bytes + 1)
        if len(payload) > maximum_bytes:
            raise ProductUnitResultUnavailable("result metadata exceeds the size limit")
        document = json.loads(payload.decode("utf-8"))
    except (ArtifactUnavailable, OSError, UnicodeError, ValueError) as exc:
        raise ProductUnitResultUnavailable from exc
    if not isinstance(document, dict):
        raise ProductUnitResultUnavailable("result metadata is not a JSON object")
    return document
