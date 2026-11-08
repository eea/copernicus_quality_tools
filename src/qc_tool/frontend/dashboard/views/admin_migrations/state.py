"""Request-local state shared by migration actions and page presentation."""

from dataclasses import dataclass, field
from datetime import datetime

from django.forms import Form


@dataclass
class MigrationPage:
    overview: dict = field(default_factory=dict)
    operation: dict | None = None
    review: dict | None = None
    activation_review: dict | None = None
    preparation_form: Form | None = None
    activation_form: Form | None = None
    checked_at: datetime | None = None
    action_error: str = ""
    status_code: int = 200
    feedback: dict = field(default_factory=dict)

    @property
    def database(self):
        return self.overview.get("database", {})
