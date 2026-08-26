"""Stable application errors for delivery submission workflows."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SubmissionError(Exception):
    """Transport-neutral failure safe to expose through browser/API adapters."""

    code: str
    message: str
    status_code: int = 409

    def __str__(self):
        return self.message


class PublicationError(SubmissionError):
    """A retryable or unsafe filesystem publication failure."""

