"""Immutable presentation values for product pages."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from typing import Tuple


@dataclass(frozen=True)
class ProductDefinitionSummary:
    ident: str
    description: str
    digest: Optional[str]
    is_primary: bool


@dataclass(frozen=True)
class ProductReleaseSummary:
    key: str
    revision: int
    description: str
    coverage_state: str
    coverage_state_label: str
    approved_at: Optional[datetime]


@dataclass(frozen=True)
class QualityCheckSummary:
    total: int
    required: int
    optional: int


@dataclass(frozen=True)
class ProductCoverageSummary:
    state: str
    expected: Optional[int]
    submitted: Optional[int]
    conflicts: Optional[int]
    remaining: Optional[int]
    completion_percentage: Optional[float]


@dataclass(frozen=True)
class ProductReleaseDetail:
    release: ProductReleaseSummary
    definitions: Tuple[ProductDefinitionSummary, ...]
    quality_checks: Optional[QualityCheckSummary]
    coverage: Optional[ProductCoverageSummary]
    remaining_aois: Optional[Tuple[str, ...]]
    remaining_aois_truncated: bool


@dataclass(frozen=True)
class ProductDetail:
    ident: str
    name: str
    description: str
    managed: bool
    releases: Tuple[ProductReleaseDetail, ...]
    releases_truncated: bool
    definitions: Tuple[ProductDefinitionSummary, ...]
    quality_checks: Optional[QualityCheckSummary]
