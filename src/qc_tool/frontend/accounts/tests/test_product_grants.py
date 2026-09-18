from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import transaction
from django.test import TestCase

from qc_tool.frontend.accounts.authorization.access import access_for
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.accounts.services.product_grants import (
    create_product_grant,
    save_product_grant,
)
from qc_tool.frontend.accounts.services.products import (
    ProductCatalogUnavailable,
)
from qc_tool.frontend.accounts.services.products import product_ident_choices


CATALOG = {
    "clc2024": "Corine Land Cover 2024",
    "general_raster": "General raster product",
}


class UserProductGrantTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="product-user")

    @patch(
        "qc_tool.frontend.accounts.services.products.available_product_descriptions",
        return_value=CATALOG,
    )
    def test_service_validates_and_creates_multiple_canonical_grants(self, _get):
        product_group = Group.objects.get(name=Role.PRODUCT_MANAGER.value)
        self.user.groups.add(product_group)

        for product_ident in CATALOG:
            create_product_grant(
                user=self.user,
                product_ident=product_ident,
            )

        access = access_for(self.user)

        self.assertEqual(access.product_idents, frozenset(CATALOG))
        self.assertTrue(access.can_view_product_deliveries)
        self.assertTrue(access.can_view_product_aggregate_report)

    @patch(
        "qc_tool.frontend.accounts.services.products.available_product_descriptions",
        return_value=CATALOG,
    )
    def test_new_values_must_exactly_match_current_canonical_keys(self, _get):
        for product_ident in ("CLC2024", " clc2024 ", "retired_product"):
            with self.subTest(product_ident=product_ident):
                with self.assertRaises(ValidationError):
                    create_product_grant(
                        user=self.user,
                        product_ident=product_ident,
                    )

    @patch(
        "qc_tool.frontend.accounts.services.products.available_product_descriptions",
        return_value=CATALOG,
    )
    def test_unchanged_unavailable_legacy_value_remains_editable(self, _get):
        grant = UserProductGrant.objects.create(
            user=self.user,
            product_ident="retired_product",
        )

        grant.full_clean()
        grant.product_ident = "another_retired_product"

        with self.assertRaises(ValidationError):
            grant.full_clean()

        grant.refresh_from_db()
        grant.user = get_user_model().objects.create_user(
            username="reassigned-product-user"
        )
        with self.assertRaises(ValidationError):
            grant.full_clean()

    @patch(
        "qc_tool.frontend.accounts.services.products.available_product_descriptions",
        return_value=CATALOG,
    )
    def test_choices_label_stored_unavailable_legacy_values(self, _get):
        choices = dict(product_ident_choices(include={"retired_product"}))

        self.assertIn("Corine Land Cover 2024", choices["clc2024"])
        self.assertIn(
            "unavailable legacy product",
            choices["retired_product"],
        )

    @patch(
        "qc_tool.frontend.accounts.services.products.available_product_descriptions",
        side_effect=ProductCatalogUnavailable("catalog offline"),
    )
    def test_catalog_failure_is_typed_and_model_validation_safe(self, _get):
        with self.assertRaises(ProductCatalogUnavailable):
            product_ident_choices()

        grant = UserProductGrant(
            user=self.user,
            product_ident="clc2024",
        )
        with self.assertRaises(ValidationError) as error:
            grant.full_clean()
        self.assertIn("product_ident", error.exception.message_dict)

    def test_database_rejects_empty_and_duplicate_grants(self):
        UserProductGrant.objects.create(
            user=self.user,
            product_ident="clc2024",
        )

        for product_ident in ("", "clc2024"):
            with self.subTest(product_ident=product_ident):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        UserProductGrant.objects.create(
                            user=self.user,
                            product_ident=product_ident,
                        )

    def test_created_by_is_optional_and_nulls_with_deleted_creator(self):
        creator = get_user_model().objects.create_user(username="product-admin")
        grant = UserProductGrant.objects.create(
            user=self.user,
            product_ident="clc2024",
            created_by=creator,
        )

        creator.delete()
        grant.refresh_from_db()

        self.assertIsNone(grant.created_by)

    @patch(
        "qc_tool.frontend.accounts.services.products.available_product_descriptions",
        return_value=CATALOG,
    )
    def test_shared_assignment_service_preserves_creator_and_validates_changes(self, _get):
        creator = get_user_model().objects.create_user(username="assigning-admin")
        editor = get_user_model().objects.create_user(username="editing-admin")
        grant = save_product_grant(
            UserProductGrant(user=self.user, product_ident="clc2024"),
            created_by=creator,
        )
        self.assertEqual(grant.created_by, creator)
        grant.product_ident = "general_raster"
        save_product_grant(grant, created_by=editor)
        grant.refresh_from_db()
        self.assertEqual(grant.created_by, creator)
        self.assertEqual(grant.product_ident, "general_raster")
        grant.product_ident = "unavailable"
        with self.assertRaises(ValidationError):
            save_product_grant(grant, created_by=editor)
        grant.refresh_from_db()
        self.assertEqual(grant.product_ident, "general_raster")
