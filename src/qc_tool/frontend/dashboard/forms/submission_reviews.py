"""Explicit, version-checked submission decisions."""

from django import forms


class SubmissionReviewForm(forms.Form):
    expected_review_version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    expected_conflict_version = forms.IntegerField(min_value=1, required=False, widget=forms.HiddenInput)
    decision = forms.ChoiceField(choices=(
        ("approved", "Approve"), ("declined", "Reject and request corrections"), ("replace", "Approve replacement"),
    ), widget=forms.HiddenInput)
    notes = forms.CharField(
        label="Feedback for the uploader", max_length=5000, required=False,
        widget=forms.Textarea(attrs={
            "rows": 4, "class": "form-control", "aria-describedby": "review-notes-help",
            "placeholder": "Add feedback about this delivery. If rejecting, explain what needs to change.",
        }),
        help_text="Shared with the uploader. Required when rejecting or choosing between competing submissions; optional for approval.",
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("decision") in {"declined", "replace"} and not cleaned.get("notes", "").strip():
            self.add_error("notes", "Give a reason and explain what the uploader needs to correct, or why another submission is being selected.")
        if cleaned.get("decision") == "replace" and not cleaned.get("expected_conflict_version"):
            self.add_error(None, "Refresh the page to review the current competing submissions.")
        return cleaned
