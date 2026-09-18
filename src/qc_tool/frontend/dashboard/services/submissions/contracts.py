"""Typed contracts shared by submission lifecycle components."""

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID


@dataclass(frozen=True)
class ReservedSubmission:
    submission_uuid: UUID
    delivery_id: int
    job_uuid: UUID
    product_release_id: int
    product_unit_id: int
    release_key: str
    product_unit_code: str
    submitted_product_unit_code: str
    username: str
    filename: str
    is_s3: bool
    expected_input_digest: str
    requested_at_iso: str
    already_existed: bool
    artifact_path: str = ""


@dataclass(frozen=True)
class PublicationReceipt:
    artifact_path: str
    artifact_digest: str
    input_digest: str
    recovered_existing: bool = False


@dataclass(frozen=True)
class SubmissionResult:
    submission_uuid: UUID
    delivery_id: int
    publication_state: str
    review_state: str
    conflict_id: int | None
    artifact_path: str
    published_at: object
    idempotent: bool

    def as_dict(self):
        return {
            "submission_id": str(self.submission_uuid),
            "delivery_id": self.delivery_id,
            "publication_status": self.publication_state,
            "review_status": self.review_state,
            "conflict_id": self.conflict_id,
            "published_at": (
                self.published_at.isoformat() if self.published_at else None
            ),
            "idempotent": self.idempotent,
        }


@dataclass(frozen=True)
class ConflictResolutionResult:
    conflict_id: int
    version: int
    selected_submission_uuid: UUID


@dataclass(frozen=True)
class PublicationLayout:
    root: Path
    final_directory: Path
    staging_directory: Path
