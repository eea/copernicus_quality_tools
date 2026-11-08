"""Bind an upgrade confirmation to the reviewed backup and maintenance window."""

from django import forms

from .data_transfers import DatabaseActivationForm


class MigrationPreparationForm(forms.Form):
    backup_id = forms.UUIDField(widget=forms.HiddenInput)
    review_hash = forms.CharField(min_length=64, max_length=64, widget=forms.HiddenInput)
    generation = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    confirmed_backup = forms.BooleanField(label=(
        "I reviewed backup coverage and authorize migrating a separate database copy "
        "with the installed migration code."
    ))


def activation_form(review, *, data=None, generation=None):
    """Bind both switch review and confirmation to the same form contract."""
    return DatabaseActivationForm(data, prefix="activation", destination=review["target_database"],
        requires_credentials=review.get("requires_credentials", False), initial={
            "review_hash": review.get("review_hash"), "revision": review.get("revision"),
            "generation": generation,
        })
