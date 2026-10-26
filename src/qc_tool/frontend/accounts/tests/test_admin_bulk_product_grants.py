"""Bulk scope assignment stays explicit, authorized and safe for large catalogs."""

import json
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from qc_tool.frontend.accounts.admin.role_permissions import synchronize_admin_role
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.accounts.services.products import ProductCatalogUnavailable


class _Inputs(HTMLParser):
    def __init__(self, response):
        super().__init__()
        self.inputs = []
        self.selects = []
        self.current_select = None
        self.feed(response.content.decode())

    def handle_starttag(self, tag, attrs):
        if tag == "input":
            self.inputs.append(dict(attrs))
        elif tag == "select":
            self.current_select = {**dict(attrs), "options": []}
            self.selects.append(self.current_select)
        elif tag == "option" and self.current_select is not None:
            self.current_select["options"].append(dict(attrs))

    def handle_endtag(self, tag):
        if tag == "select":
            self.current_select = None


@override_settings(MAINTENANCE_MODE=False)
class BulkProductGrantAdminTests(TestCase):
    def setUp(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(override_settings(
            QC_TOOL_MAINTENANCE_DIR=directory / "maintenance",
            QC_TOOL_TRANSFER_DIR=directory / "transfers",
        ))
        self.catalog = {
            "clms_euhydro_alpha": "River network",
            "clms_euhydro_beta": "Water bodies",
            "clms_hrlvlcc_alpha": "Land cover",
            "clms_other_alpha": "Other product",
        }
        self.enterContext(patch(
            "qc_tool.frontend.accounts.services.products.available_product_descriptions",
            side_effect=lambda: self.catalog,
        ))
        self.user_model = get_user_model()
        self.actor = self.user_model.objects.create_user(username="bulk-grant-administrator")
        self.admin_group = synchronize_admin_role()
        self.actor.groups.add(self.admin_group)
        self.client.force_login(self.actor)
        self.target = self.user_model.objects.create_user(username="bulk-grant-target")
        self.change_url = reverse("admin:auth_user_change", args=[self.target.pk])

    def management_data(self, grants=()):
        grants = list(grants)
        data = {
            "personal_access_tokens-TOTAL_FORMS": "0",
            "personal_access_tokens-INITIAL_FORMS": "0",
            "product_grants-TOTAL_FORMS": str(len(grants)),
            "product_grants-INITIAL_FORMS": str(len(grants)),
            "product_grants-MIN_NUM_FORMS": "0",
            "product_grants-MAX_NUM_FORMS": "1000",
        }
        for index, grant in enumerate(grants):
            data[f"product_grants-{index}-id"] = str(grant.pk)
            data[f"product_grants-{index}-product_ident"] = grant.product_ident
        return data

    def change_data(self, products=(), *, grants=(), **changes):
        data = {
            "first_name": self.target.first_name,
            "last_name": self.target.last_name,
            "email": self.target.email,
            "is_active": "on",
            "groups": list(self.target.groups.values_list("pk", flat=True)),
            "product_grants-bulk-products": json.dumps(list(products)),
            "_save": "Save",
            **self.management_data(grants),
        }
        data.update(changes)
        return data

    def test_bulk_add_audits_exact_selected_scopes_without_changing_roles(self):
        selected = ["clms_euhydro_alpha", "clms_hrlvlcc_alpha"]
        roles = set(self.target.groups.values_list("name", flat=True))

        response = self.client.post(self.change_url, self.change_data(selected))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(set(self.target.product_grants.values_list("product_ident", flat=True)), set(selected))
        self.assertEqual(set(self.target.product_grants.values_list("created_by_id", flat=True)), {self.actor.pk})
        self.assertEqual(set(self.target.groups.values_list("name", flat=True)), roles)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_staff)
        self.assertFalse(self.target.is_superuser)
        self.assertFalse(self.target.user_permissions.exists())

    def test_bulk_widget_loads_shared_selection_before_its_feature_script(self):
        response = self.client.get(self.change_url)
        shared = "dashboard/js/shared/checkbox-selection.js"
        feature = "accounts/js/admin/bulk-product-select.js"
        self.assertContains(response, shared, count=1)
        self.assertContains(response, feature, count=1)
        html = response.content.decode()
        self.assertLess(html.index(shared), html.index(feature))

    def test_bulk_assignment_on_add_user_uses_the_same_validated_path(self):
        selected = ["clms_euhydro_alpha", "clms_euhydro_beta"]
        response = self.client.post(reverse("admin:auth_user_add"), {
            "username": "new-bulk-grant-user",
            "password1": "sufficient-test-password",
            "password2": "sufficient-test-password",
            "product_grants-bulk-products": json.dumps(selected),
            "_save": "Save",
            **self.management_data(),
        })

        self.assertEqual(response.status_code, 302)
        user = self.user_model.objects.get(username="new-bulk-grant-user")
        self.assertEqual(set(user.product_grants.values_list("product_ident", flat=True)), set(selected))
        self.assertEqual(set(user.product_grants.values_list("created_by_id", flat=True)), {self.actor.pk})
        self.assertEqual(set(user.groups.values_list("name", flat=True)), {Role.DEFAULT.value})

    def test_untouched_rendered_extra_row_does_not_add_an_unselected_scope(self):
        rendered = _Inputs(self.client.get(self.change_url))
        management = {
            field["name"]: field.get("value", "")
            for field in rendered.inputs
            if field.get("name", "").startswith("product_grants-")
            and field.get("type") == "hidden"
        }
        self.assertEqual(management["product_grants-TOTAL_FORMS"], "1")
        self.assertEqual(management["product_grants-INITIAL_FORMS"], "0")
        extra = next(field for field in rendered.selects if field.get("name") == "product_grants-0-product_ident")
        self.assertEqual(extra["options"][0]["value"], "")
        default = next((option for option in extra["options"] if "selected" in option), extra["options"][0])
        self.assertEqual(default["value"], "")

        data = {**self.change_data(), **management}
        data["product_grants-0-product_ident"] = default["value"]
        data["product_grants-bulk-products"] = json.dumps(["clms_hrlvlcc_alpha"])
        response = self.client.post(self.change_url, data)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(self.target.product_grants.values_list("product_ident", flat=True)), ["clms_hrlvlcc_alpha"])

    def test_existing_assignment_keeps_its_creator_when_selected_again(self):
        existing = UserProductGrant.objects.create(
            user=self.target, product_ident="clms_euhydro_alpha", created_by=self.target,
        )
        response = self.client.post(self.change_url, self.change_data(
            [existing.product_ident, "clms_euhydro_beta"], grants=[existing],
        ))

        self.assertEqual(response.status_code, 302)
        existing.refresh_from_db()
        self.assertEqual(existing.created_by_id, self.target.pk)
        self.assertEqual(self.target.product_grants.count(), 2)
        self.assertEqual(self.target.product_grants.get(product_ident="clms_euhydro_beta").created_by_id, self.actor.pk)

    def test_invalid_bulk_payload_rejects_the_whole_user_change(self):
        existing = UserProductGrant.objects.create(user=self.target, product_ident="clms_other_alpha")
        for payload in (
            "not-json", "{}", '"clms_euhydro_alpha"', "null", "[3]", '[""]',
            '["not-configured"]', '["clms_euhydro_alpha", "clms_euhydro_alpha"]',
            '["clms_euhydro_alpha", "not-configured"]',
        ):
            with self.subTest(payload=payload):
                response = self.client.post(self.change_url, self.change_data(
                    grants=[existing], first_name="Must not be saved",
                    **{"product_grants-bulk-products": payload},
                ))

                self.assertEqual(response.status_code, 200)
                self.target.refresh_from_db()
                self.assertEqual(self.target.first_name, "")
                self.assertEqual(list(self.target.product_grants.values_list("product_ident", flat=True)), [existing.product_ident])

    def test_bulk_add_and_inline_delete_cannot_contradict_each_other(self):
        existing = UserProductGrant.objects.create(user=self.target, product_ident="clms_euhydro_alpha")
        response = self.client.post(self.change_url, self.change_data(
            [existing.product_ident, "clms_euhydro_beta"], grants=[existing],
            first_name="Must not be saved", **{"product_grants-0-DELETE": "on"},
        ))

        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.first_name, "")
        self.assertEqual(list(self.target.product_grants.values_list("product_ident", flat=True)), [existing.product_ident])

    def test_invalid_bulk_payload_does_not_create_a_partial_new_account(self):
        response = self.client.post(reverse("admin:auth_user_add"), {
            "username": "invalid-bulk-new-user",
            "password1": "sufficient-test-password",
            "password2": "sufficient-test-password",
            "product_grants-bulk-products": '["clms_euhydro_alpha", "not-configured"]',
            "_save": "Save",
            **self.management_data(),
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.user_model.objects.filter(username="invalid-bulk-new-user").exists())

    def test_user_validation_keeps_explicit_bulk_choices_without_saving_them(self):
        selected = ["clms_euhydro_alpha", "clms_euhydro_beta"]
        response = self.client.post(self.change_url, self.change_data(selected, email="invalid-email"))

        self.assertEqual(response.status_code, 200)
        field = next(field for field in _Inputs(response).inputs if field.get("name") == "product_grants-bulk-products")
        self.assertEqual(json.loads(field["value"]), selected)
        self.assertFalse(self.target.product_grants.exists())

    def test_unavailable_catalog_rejects_bulk_and_other_user_changes(self):
        existing = UserProductGrant.objects.create(user=self.target, product_ident="clms_other_alpha")
        with self.assertLogs("qc_tool.frontend.accounts.admin.products", level="WARNING"), patch(
            "qc_tool.frontend.accounts.services.products.available_product_descriptions",
            side_effect=ProductCatalogUnavailable("Unavailable test catalog"),
        ):
            response = self.client.post(self.change_url, self.change_data(
                ["clms_euhydro_alpha"], grants=[existing], first_name="Must not be saved",
            ))

        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.first_name, "")
        self.assertEqual(list(self.target.product_grants.values_list("product_ident", flat=True)), [existing.product_ident])

    def test_830_scopes_fit_default_request_limits_and_existing_rows_stay_bounded(self):
        self.catalog = {f"clms_euhydro_{index:04}": f"Definition {index}" for index in range(830)}
        self.assertEqual(settings.DATA_UPLOAD_MAX_NUMBER_FIELDS, 1000)
        response = self.client.get(self.change_url)
        inputs = _Inputs(response).inputs
        bulk_inputs = [field for field in inputs if field.get("name") == "product_grants-bulk-products"]
        self.assertEqual(len(bulk_inputs), 1)
        self.assertEqual(bulk_inputs[0]["type"], "hidden")
        choices = [field for field in inputs if "data-bulk-product-choice" in field]
        self.assertEqual(len(choices), 830)
        self.assertTrue(all("name" not in field for field in choices))

        saved = self.client.post(self.change_url, self.change_data(self.catalog))

        self.assertEqual(saved.status_code, 302)
        self.assertEqual(self.target.product_grants.count(), 830)
        self.assertEqual(set(self.target.product_grants.values_list("created_by_id", flat=True)), {self.actor.pk})
        rendered = self.client.get(self.change_url)
        formset = next(
            inline.formset for inline in rendered.context["inline_admin_formsets"]
            if inline.formset.model is UserProductGrant
        )
        self.assertEqual(formset.initial_form_count(), 40)
        self.assertLessEqual(formset.total_form_count(), 41)
        self.assertContains(rendered, reverse("admin:accounts_userproductgrant_changelist"))
        visible = list(formset.get_queryset())
        repeated = self.client.post(self.change_url, self.change_data(self.catalog, grants=visible))
        self.assertEqual(repeated.status_code, 302)
        self.assertEqual(self.target.product_grants.count(), 830)

    def test_generic_user_edit_permission_does_not_allow_bulk_assignment(self):
        actor = self.user_model.objects.create_user(username="ordinary-user-editor")
        actor.user_permissions.add(*Permission.objects.filter(codename__in=("change_user", "add_userproductgrant")))
        self.user_model.objects.filter(pk=actor.pk).update(is_staff=True)
        self.client.force_login(actor)
        self.assertNotContains(self.client.get(self.change_url), 'name="product_grants-bulk-products"')

        response = self.client.post(self.change_url, self.change_data(["clms_euhydro_alpha"]))

        self.assertIn(response.status_code, (200, 403))
        self.assertFalse(self.target.product_grants.exists())

    def test_admin_without_add_grant_permission_cannot_use_the_bulk_field(self):
        self.admin_group.permissions.remove(Permission.objects.get(codename="add_userproductgrant"))
        response = self.client.get(self.change_url)
        self.assertNotContains(response, 'name="product_grants-bulk-products"')

        rejected = self.client.post(self.change_url, self.change_data(["clms_euhydro_alpha"]))

        self.assertIn(rejected.status_code, (200, 403))
        self.assertFalse(self.target.product_grants.exists())

    def test_role_administrator_cannot_bulk_assign_to_a_protected_superuser(self):
        target = self.user_model.objects.create_superuser(username="protected-bulk-root", email="root@example.test")
        response = self.client.post(reverse("admin:auth_user_change", args=[target.pk]), self.change_data(["clms_euhydro_alpha"]))

        self.assertEqual(response.status_code, 403)
        self.assertFalse(target.product_grants.exists())

    def test_maintenance_blocks_bulk_assignment_and_other_form_changes(self):
        with override_settings(MAINTENANCE_MODE=True):
            response = self.client.post(self.change_url, self.change_data(["clms_euhydro_alpha"], first_name="Must not be saved"))

        self.assertEqual(response.status_code, 503)
        self.target.refresh_from_db()
        self.assertEqual(self.target.first_name, "")
        self.assertFalse(self.target.product_grants.exists())

    def test_bulk_assignment_still_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.actor)
        response = client.post(self.change_url, self.change_data(["clms_euhydro_alpha"]))

        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.target.product_grants.exists())
