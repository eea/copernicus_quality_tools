"""Bind database action buttons to the copy and state displayed to an admin."""

from django import forms


class DeleteDatabaseForm(forms.Form):
    generation = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    destination_confirmation = forms.CharField(max_length=256, strip=False, widget=forms.HiddenInput,
        error_messages={"required": "The selected database is missing. Reload the list and try again."})

    def __init__(self, *args, database, **kwargs):
        self.database = database
        super().__init__(*args, **kwargs)
        self.initial["destination_confirmation"] = database

    def clean_destination_confirmation(self):
        value = self.cleaned_data["destination_confirmation"]
        if value != self.database:
            raise forms.ValidationError("The selected database has changed. Reload the list and try again.")
        return value
