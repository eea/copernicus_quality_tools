"""Public job failures shared by worker results and frontend presentation."""

from qc_tool.boundaries.errors import BoundaryGenerationUnavailable, BoundaryPackageError


UNEXPECTED_JOB_ERROR = (
    "The QC job failed unexpectedly. Contact an administrator "
    "and provide the job identifier."
)
BOUNDARY_UNAVAILABLE_MESSAGE = (
    "No active boundary package is available. An administrator must activate "
    "boundary data before QC can run."
)


def public_job_failure(error):
    """Expose typed safe failures; keep unexpected exception details in logs."""
    if isinstance(error, BoundaryPackageError):
        message = (BOUNDARY_UNAVAILABLE_MESSAGE if isinstance(error, BoundaryGenerationUnavailable)
                   else error.user_message)
        return {"error_code": error.code, "error_message": message}
    return {"error_message": UNEXPECTED_JOB_ERROR}
