"""Shared execution prerequisites for browser and API QC job admission."""

from django.urls import reverse

from qc_tool.boundaries import BoundaryPackageError, resolve_boundary_generation
from qc_tool.common import CONFIG


class JobPrerequisiteUnavailable(ValueError):
    """A known deployment prerequisite is missing; no QC job should be queued."""

    status_code = 503

    def __init__(self, error):
        self.code = error.code
        self.message = (
            f"{error.user_message} An administrator must upload or restore and "
            "activate a valid boundary package in Admin → Boundaries before QC can run."
        )
        super().__init__(self.message)


def require_job_prerequisites():
    """Use the worker's shared resolver without changing files or activation."""
    try:
        return resolve_boundary_generation(CONFIG["boundary_dir"])
    except BoundaryPackageError as error:
        raise JobPrerequisiteUnavailable(error) from error


def job_prerequisite_context(account_access):
    """Keep operator destinations limited to administrators who can use them."""
    try:
        require_job_prerequisites()
    except JobPrerequisiteUnavailable as error:
        can_manage = account_access.is_administrator and account_access.can_manage_configuration
        return {
            "available": False, "code": error.code,
            "message": error.message if can_manage else (
                "QC is unavailable because the boundary package needs administrator attention. "
                "Contact an administrator before starting QC."
            ),
            "admin_url": reverse("boundaries") if can_manage else "",
        }
    return {"available": True, "code": "", "message": "", "admin_url": ""}
