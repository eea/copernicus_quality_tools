"""Immutable contracts for product unit result ingestion."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ProductUnitUpdateAction(str, Enum):
    """How a worker result should affect an already persisted product unit."""

    PRESERVE = "preserve"
    CLEAR = "clear"
    SET = "set"


@dataclass(frozen=True)
class ProductUnitResultUpdate:
    action: ProductUnitUpdateAction
    value: Optional[str] = None
    conflicted: bool = False
