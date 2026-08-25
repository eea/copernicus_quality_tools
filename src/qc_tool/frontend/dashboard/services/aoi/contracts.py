"""Immutable contracts for AOI result ingestion."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class AoiUpdateAction(str, Enum):
    """How a worker result should affect an already persisted AOI."""

    PRESERVE = "preserve"
    CLEAR = "clear"
    SET = "set"


@dataclass(frozen=True)
class AoiResultUpdate:
    action: AoiUpdateAction
    value: Optional[str] = None
