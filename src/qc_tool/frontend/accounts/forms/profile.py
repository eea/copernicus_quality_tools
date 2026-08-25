"""Strictly scoped forms for editing the current user's public details."""

from django import forms
from django.contrib.auth import get_user_model


class AccountProfileForm(forms.ModelForm):
    """Edit personal details without exposing authentication or access fields."""

    class Meta:
        model = get_user_model()
        fields = ("first_name", "last_name", "email")
        widgets = {
            "first_name": forms.TextInput(
                attrs={
                    "autocomplete": "given-name",
                    "class": "form-control",
                }
            ),
            "last_name": forms.TextInput(
                attrs={
                    "autocomplete": "family-name",
                    "class": "form-control",
                }
            ),
            "email": forms.EmailInput(
                attrs={
                    "autocomplete": "email",
                    "class": "form-control",
                }
            ),
        }

    def clean_email(self):
        """Normalize the domain while retaining Django's email validation."""

        email = self.cleaned_data["email"]
        return get_user_model().objects.normalize_email(email)
