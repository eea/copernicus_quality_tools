"""Bind a bulk decision to the receipt versions actually shown to a reviewer."""

from uuid import UUID

from django import forms
from django.core import signing

from qc_tool.frontend.dashboard.services.submissions.bulk_review import MAX_BULK_APPROVALS


_SELECTION_SALT = "dashboard.submission.bulk-approval"
_SELECTION_MAX_AGE = 60 * 60


def submission_selection_token(submission, reviewer_id):
    return signing.dumps({
        "id": str(submission.pk), "version": submission.review_version,
        "reviewer": reviewer_id,
    }, salt=_SELECTION_SALT)


class BulkSubmissionReviewForm(forms.Form):
    selection = forms.Field(
        widget=forms.MultipleHiddenInput,
        error_messages={"required": "Select at least one delivery to approve."},
    )
    intent = forms.ChoiceField(choices=(("preview", "Preview"), ("approve", "Approve")))
    notes = forms.CharField(
        label="Feedback for the uploaders (optional)", required=False, max_length=5000,
        help_text="The same feedback will be saved with each approval and shared with its uploader.",
        widget=forms.Textarea(attrs={"rows": 3, "class": "form-control", "aria-describedby": "bulk-notes-help"}),
    )

    def __init__(self, *args, reviewer_id, **kwargs):
        super().__init__(*args, **kwargs)
        self.reviewer_id = reviewer_id
        self.selections = []

    def clean_selection(self):
        tokens = self.cleaned_data["selection"]
        if not isinstance(tokens, list) or not 1 <= len(tokens) <= MAX_BULK_APPROVALS:
            raise forms.ValidationError("Select between 1 and {} deliveries on one page.".format(MAX_BULK_APPROVALS))
        seen = set()
        for token in tokens:
            try:
                payload = signing.loads(token, salt=_SELECTION_SALT, max_age=_SELECTION_MAX_AGE)
                ident = UUID(payload["id"])
                version = payload["version"]
                if payload["reviewer"] != self.reviewer_id or type(version) is not int or version < 0 or ident in seen:
                    raise ValueError
            except (signing.BadSignature, ValueError, KeyError, TypeError, AttributeError):
                raise forms.ValidationError("Your selection has expired or is invalid. Return to the list and select the deliveries again.")
            seen.add(ident)
            self.selections.append((ident, version))
        return tokens
