"""Specification selection follows explicit series, with scoped retained history."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from qc_tool.frontend.accounts.authorization import access_for
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.dashboard.models import ProductRelease, ProductReleaseDefinition, QcDefinition
from qc_tool.frontend.dashboard.services.products.specification_history import specification_history
from qc_tool.frontend.dashboard.tests.catalog_fixtures import managed_definition


class SpecificationHistoryTests(TestCase):
    def setUp(self):
        self.definition, self.release = managed_definition("stable-product")
        self.user = get_user_model().objects.create_user(username="history-reader")
        UserProductGrant.objects.create(user=self.user, product_ident="stable-product")

    def history(self, user=None):
        return specification_history(
            "stable-product", access_for(user or self.user), page_number=1,
        )[1]

    def test_newer_unselected_upload_does_not_become_current(self):
        newer = QcDefinition.objects.create(
            product_ident="stable-product", digest="b" * 64, description="Not selected",
            document={"steps": []}, source_path="fixture:newer.json",
        )
        rows = self.history()
        self.assertEqual(rows[0]["digest"], newer.digest)
        self.assertFalse(rows[0]["is_current"])
        self.assertTrue(rows[1]["is_current"])
        self.assertEqual(rows[1]["series"][0]["revision"], 1)

    def test_coverage_revision_can_keep_identical_specification_bytes(self):
        self.release.is_current = False
        self.release.save(update_fields=("is_current",))
        current = ProductRelease.objects.create(
            product=self.release.product, release_key=self.release.release_key, revision=2,
            catalog_digest="c" * 64, is_current=True, supersedes=self.release,
        )
        ProductReleaseDefinition.objects.create(
            product_release=current, qc_definition=self.definition, is_primary=True,
        )
        row, = self.history()
        self.assertTrue(row["is_current"])
        self.assertEqual([item["revision"] for item in row["series"]], [2, 1])
        self.assertEqual([item["is_current"] for item in row["series"]], [True, False])

    def test_parallel_series_each_keep_their_selected_current_specification(self):
        definition = QcDefinition.objects.create(
            product_ident="alternate-recipe", digest="d" * 64, description="Alternate",
            document={"steps": []}, source_path="fixture:alternate.json",
        )
        parallel = ProductRelease.objects.create(
            product=self.release.product, release_key="parallel-series", revision=1,
            catalog_digest="e" * 64, is_current=True,
        )
        ProductReleaseDefinition.objects.create(
            product_release=parallel, qc_definition=definition, is_primary=True,
        )
        rows = self.history()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["is_current"] for row in rows))

    def test_recipe_grant_includes_only_that_recipe_history(self):
        recipe = QcDefinition.objects.create(
            product_ident="assigned-recipe", digest="f" * 64, description="Assigned recipe",
            document={"steps": []}, source_path="fixture:recipe.json",
        )
        ProductReleaseDefinition.objects.create(
            product_release=self.release, qc_definition=recipe,
        )
        reader = get_user_model().objects.create_user(username="recipe-reader")
        UserProductGrant.objects.create(user=reader, product_ident=recipe.product_ident)
        row, = self.history(reader)
        self.assertEqual(row["ident"], recipe.product_ident)
        self.assertEqual(row["digest"], recipe.digest)

    def test_parent_grant_does_not_reveal_unlinked_versions_of_a_shared_recipe(self):
        linked = QcDefinition.objects.create(
            product_ident="shared-recipe", digest="1" * 64, description="Linked version",
            document={"steps": []}, source_path="fixture:linked.json",
        )
        ProductReleaseDefinition.objects.create(
            product_release=self.release, qc_definition=linked,
        )
        private = QcDefinition.objects.create(
            product_ident="shared-recipe", digest="2" * 64, description="Other product version",
            document={"steps": []}, source_path="fixture:private.json",
        )
        digests = {row["digest"] for row in self.history()}
        self.assertIn(linked.digest, digests)
        self.assertNotIn(private.digest, digests)
