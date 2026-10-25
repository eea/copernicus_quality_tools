"""Full database package selections and reviewed import confirmations."""

from django import forms
from django.contrib.auth import get_user_model

from qc_tool.database.transfers.components import EXPORT_COMPONENT_CHOICES, EXPORT_COMPONENTS


def _file_selection_field():
    return forms.TypedChoiceField(
        label="Packaged files", required=False, coerce=lambda value: value == "true", empty_value=None,
        choices=(("true", "Include packaged files"), ("false", "Skip packaged files")),
        widget=forms.RadioSelect,
    )


class ExportSelectionForm(forms.Form):
    scope = forms.ChoiceField(
        choices=(("database", "Complete database"),), initial="database",
        widget=forms.HiddenInput,
    )
    components = forms.MultipleChoiceField(
        label="Additional package sections", required=False,
        choices=EXPORT_COMPONENT_CHOICES, initial=EXPORT_COMPONENTS,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial.setdefault("scope", "database")
        self.initial.setdefault("components", list(EXPORT_COMPONENTS))
        if self.is_bound and "scope" not in self.data:
            self.data = self.data.copy()
            self.data["scope"] = "database"

    def selection(self):
        selected = set(self.cleaned_data["components"])
        return {
            "profile": "database", "user_ids": [],
            "components": [key for key in EXPORT_COMPONENTS if key in selected],
        }


class UploadPackageForm(forms.Form):
    package = forms.FileField(
        label="QC Tool package (.zip)",
        help_text="Choose a QC Tool ZIP. Its format and restore destination are identified before you confirm.",
        widget=forms.ClearableFileInput(attrs={"accept": ".zip,application/zip"}),
    )
    include_files = _file_selection_field()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial.setdefault("include_files", "true")


class ReviewedActionForm(forms.Form):
    reviewed_hash = forms.CharField(max_length=64, min_length=64, widget=forms.HiddenInput)
    generation = forms.IntegerField(min_value=0, widget=forms.HiddenInput)


class ImportConfirmationForm(forms.Form):
    plan_hash = forms.CharField(max_length=64, min_length=64, widget=forms.HiddenInput)
    generation = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    destination_confirmation = forms.CharField(label="Confirm destination", max_length=256)
    confirmed_scope = forms.BooleanField(
        label="I reviewed the records and account mappings.",
    )

    def __init__(self, *args, confirmation_text, profile="accounts", **kwargs):
        self.confirmation_text = confirmation_text
        super().__init__(*args, **kwargs)
        self.fields["destination_confirmation"].help_text = f"Type {confirmation_text} to confirm this destination."
        if profile == "database":
            self.fields["destination_confirmation"].widget = forms.HiddenInput()
            self.fields["destination_confirmation"].help_text = ""
            self.initial["destination_confirmation"] = confirmation_text
            self.fields["confirmed_scope"].label = (
                "I trust the source of this database backup and authorize restoring all records, "
                "including credentials and permissions, by executing its SQL in this separate database."
            )
        elif profile == "application":
            self.fields["confirmed_scope"].label = (
                "I reviewed the additions, account identities and delivery files. Existing records stay unchanged."
            )
        elif profile == "accounts":
            self.fields["confirmed_scope"].label = (
                "I reviewed the selected users and profile updates. Existing passwords, access and history are preserved."
            )

    def clean_destination_confirmation(self):
        value = self.cleaned_data["destination_confirmation"]
        if not self.confirmation_text or value != self.confirmation_text:
            raise forms.ValidationError("Enter the destination exactly as displayed in the review.")
        return value


class DatabaseControlForm(forms.Form):
    generation = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    destination_confirmation = forms.CharField(max_length=256, strip=False, widget=forms.HiddenInput,
        error_messages={"required": "The selected database is missing. Reload the page and try again."})
    confirmed_storage = forms.BooleanField(
        label="I reviewed file availability and administrator access. Keep maintenance on after switching.",
    )
    username = forms.CharField(label="Administrator on the destination", max_length=150, required=False,
                               widget=forms.TextInput(attrs={"autocomplete": "username"}))
    password = forms.CharField(label="Destination administrator password", required=False, strip=False,
                               widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "current-password"}))

    def __init__(self, *args, destination, requires_credentials=False, **kwargs):
        self.destination = destination
        self.requires_credentials = requires_credentials
        super().__init__(*args, **kwargs)
        self.initial["destination_confirmation"] = destination
        self.fields["username"].required = requires_credentials
        self.fields["password"].required = requires_credentials

    def clean_destination_confirmation(self):
        value = self.cleaned_data["destination_confirmation"]
        if not self.destination or value != self.destination:
            raise forms.ValidationError("The selected database has changed. Reload the page and try again.")
        return value


class DatabaseActivationForm(DatabaseControlForm):
    review_hash = forms.CharField(max_length=64, min_length=64, widget=forms.HiddenInput)


class AccountMappingForm(forms.Form):
    """Only server-validated source accounts may become mapping form fields."""

    def __init__(self, *args, accounts, profile="accounts", **kwargs):
        super().__init__(*args, **kwargs)
        self.rows = []
        targets = get_user_model().objects.order_by("username", "pk")
        for index, account in enumerate(accounts):
            field_name = f"account_{index}"
            self.fields[field_name] = forms.ModelChoiceField(
                label=account.get("username") or str(account["source_id"]),
                required=bool(account.get("requires_mapping")),
                empty_label="Create a new inactive account",
                queryset=targets.filter(username=account.get("username")) if profile == "application" else targets,
                initial=account.get("target_id"),
            )
            self.rows.append({"source": account, "field": self[field_name]})
        self.accounts = accounts

    def mappings(self):
        return {
            str(account["source_id"]): (
                self.cleaned_data[f"account_{index}"].pk
                if self.cleaned_data[f"account_{index}"] is not None else None
            )
            for index, account in enumerate(self.accounts)
        }


class AccountChoiceForm(forms.Form):
    """Bind account decisions to the exact source rows in a reviewed page."""

    account_plan_hash = forms.CharField(min_length=64, max_length=64, widget=forms.HiddenInput)

    def __init__(self, *args, accounts, plan_hash, **kwargs):
        self.accounts = accounts
        self.plan_hash = plan_hash
        initial = dict(kwargs.pop("initial", {}) or {})
        initial["account_plan_hash"] = plan_hash
        super().__init__(*args, initial=initial, **kwargs)
        self.rows = []
        if self.is_bound:
            self.data = self.data.copy()
        for index, account in enumerate(accounts):
            action_name, target_name = f"account_action_{index}", f"account_target_{index}"
            choices = [(choice["value"], "Update profile" if choice["value"] == "replace" else choice["label"])
                       for choice in account.get("choices", [])
                       if choice.get("value") in {"import", "reuse", "replace", "skip"}]
            self.fields[action_name] = forms.ChoiceField(
                label="What to do", choices=[("", "Choose an action"), *choices],
                initial=account.get("disposition") or "",
            )
            candidates = [row["id"] for row in account.get("candidate_targets", [])
                          if type(row.get("id")) is int and row["id"] > 0]
            single_target = next((row for row in account.get("candidate_targets", [])
                                  if row.get("id") == candidates[0]), None) if len(candidates) == 1 else None
            self.fields[target_name] = forms.ModelChoiceField(
                label="Existing user", required=False, empty_label="Choose an existing user",
                queryset=get_user_model().objects.filter(pk__in=candidates).order_by("username", "pk"),
                initial=account.get("target_id") or (single_target["id"] if single_target else None),
                widget=forms.HiddenInput if single_target else forms.Select,
            )
            if self.is_bound and self.data.get(action_name) in {"import", "skip"}:
                self.data[target_name] = ""
            self.rows.append({"source": account, "action": self[action_name], "target": self[target_name],
                              "single_target": single_target})

    def clean_account_plan_hash(self):
        value = self.cleaned_data["account_plan_hash"]
        if not self.plan_hash or value != self.plan_hash:
            raise forms.ValidationError("The user review changed. Refresh it before saving these choices.")
        return value

    def clean(self):
        cleaned = super().clean()
        for index, _account in enumerate(self.accounts):
            if cleaned.get(f"account_action_{index}") in {"reuse", "replace"} and not cleaned.get(f"account_target_{index}"):
                self.add_error(f"account_target_{index}", "Choose the existing user for this action.")
        return cleaned

    def choices(self, existing=None):
        result = dict(existing or {})
        for index, account in enumerate(self.accounts):
            target = self.cleaned_data.get(f"account_target_{index}")
            result[str(account["source_id"])] = {
                "action": self.cleaned_data[f"account_action_{index}"],
                "target_id": target.pk if target is not None else None,
            }
        return result


class RecordResolutionForm(forms.Form):
    """Choices and source identities come exclusively from the reviewed plan."""

    resolution_plan_hash = forms.CharField(min_length=64, max_length=64, widget=forms.HiddenInput)

    def __init__(self, *args, conflicts, plan_hash, **kwargs):
        self.conflicts = conflicts
        self.plan_hash = plan_hash
        initial = dict(kwargs.pop("initial", {}) or {})
        initial["resolution_plan_hash"] = plan_hash
        super().__init__(*args, initial=initial, **kwargs)
        self.rows = []
        for index, conflict in enumerate(conflicts):
            field_name = f"resolution_{index}"
            # The service owns which compatible dispositions exist. HTML and
            # posted source IDs must never broaden these choices.
            choices = [(choice["value"], choice["label"]) for choice in conflict.get("choices", [])
                       if choice.get("value") in {"skip", "reuse"}]
            self.fields[field_name] = forms.ChoiceField(
                label="Action for incoming record", required=False,
                choices=[("", "Choose a safe action"), *choices],
                initial=conflict.get("resolution") or "",
                widget=forms.Select(attrs={"aria-label": "Action for incoming record: " +
                                           (conflict.get("label") or conflict["key"])}),
            )
            self.rows.append({"source": conflict, "field": self[field_name]})

    def clean_resolution_plan_hash(self):
        value = self.cleaned_data["resolution_plan_hash"]
        if not self.plan_hash or value != self.plan_hash:
            raise forms.ValidationError("The import review changed. Refresh it before saving these choices.")
        return value

    def resolutions(self, existing=None):
        result = dict(existing or {})
        for index, conflict in enumerate(self.conflicts):
            value = self.cleaned_data[f"resolution_{index}"]
            if value:
                result[conflict["key"]] = value
            else:
                result.pop(conflict["key"], None)
        return result


