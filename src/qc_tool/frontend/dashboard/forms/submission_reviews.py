"""Explicit, version-checked submission decisions."""

from django import forms


class SubmissionReviewForm(forms.Form):
    expected_review_version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    expected_conflict_version = forms.IntegerField(min_value=1, required=False, widget=forms.HiddenInput)
    decision = forms.ChoiceField(choices=(
        ("approved", "Approve"), ("declined", "Decline"), ("replace", "Approve replacement"),
    ), widget=forms.HiddenInput)
    notes = forms.CharField(
        label="Review notes", max_length=5000, required=False,
        widget=forms.Textarea(attrs={"rows": 4, "class": "form-control"}),
        help_text="Explain a decline or replacement so the uploader knows what to correct.",
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("decision") in {"declined", "replace"} and not cleaned.get("notes", "").strip():
            self.add_error("notes", "Give a reason for declining or replacing a submission.")
        if cleaned.get("decision") == "replace" and not cleaned.get("expected_conflict_version"):
            self.add_error(None, "Refresh the page to review the current competing submissions.")
        return cleaned
