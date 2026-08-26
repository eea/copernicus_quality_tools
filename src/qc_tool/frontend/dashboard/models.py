"""Django model-discovery and backward-compatible import boundary.

The deployed app label remains ``dashboard``. Model implementations are owned
by focused modules under :mod:`qc_tool.frontend.dashboard.domain`; importing
them here preserves Django discovery and every historical caller of
``dashboard.models``.
"""

from qc_tool.frontend.dashboard.domain.accounts import PersonalAccessToken
from qc_tool.frontend.dashboard.domain.accounts import UserProfile
from qc_tool.frontend.dashboard.domain.catalog import Product
from qc_tool.frontend.dashboard.domain.catalog import ProductAOI
from qc_tool.frontend.dashboard.domain.catalog import ProductRelease
from qc_tool.frontend.dashboard.domain.catalog import ProductReleaseDefinition
from qc_tool.frontend.dashboard.domain.catalog import QcDefinition
from qc_tool.frontend.dashboard.domain.deliveries import Delivery
from qc_tool.frontend.dashboard.domain.jobs import Job
from qc_tool.frontend.dashboard.domain.jobs import pull_job
from qc_tool.frontend.dashboard.domain.storage import S3Info
from qc_tool.frontend.dashboard.domain.submissions import DeliverySubmission
from qc_tool.frontend.dashboard.domain.submissions import SubmissionConflict
from qc_tool.frontend.dashboard.domain.submissions import SubmissionConflictEvent
from qc_tool.frontend.dashboard.services.products import find_product_description


__all__ = (
    "Delivery",
    "DeliverySubmission",
    "Job",
    "PersonalAccessToken",
    "Product",
    "ProductAOI",
    "ProductRelease",
    "ProductReleaseDefinition",
    "QcDefinition",
    "S3Info",
    "SubmissionConflict",
    "SubmissionConflictEvent",
    "UserProfile",
    "find_product_description",
    "pull_job",
)
