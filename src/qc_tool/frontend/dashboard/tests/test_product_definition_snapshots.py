"""Product metadata links resolve immutable database definition revisions."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.dashboard.models import Product
from qc_tool.frontend.dashboard.models import ProductRelease
from qc_tool.frontend.dashboard.models import ProductReleaseDefinition
from qc_tool.frontend.dashboard.models import QcDefinition


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class ProductDefinitionSnapshotTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="definition-snapshot-reader",
            password="test-password",
        )
        self.client.force_login(self.user)
        UserProductGrant.objects.create(user=self.user, product_ident="example")
        self.document = {
            "description": "Stored product definition",
            "steps": [{
                "check_ident": "qc_tool.vector.naming",
                "required": True,
                "parameters": {"aoi_codes": ["CZ", "SK"]},
            }],
        }
        self.payload = json.dumps(self.document).encode("utf-8")
        self.definition = QcDefinition.objects.create(
            product_ident="example",
            digest=hashlib.sha256(self.payload).hexdigest(),
            description=self.document["description"],
            document=self.document,
            source_path="/unavailable/example.json",
        )
        self.url = reverse("product_definition_json", args=("example",))

    @patch(
        "qc_tool.frontend.dashboard.views.products.data.locate_product_definition",
        side_effect=AssertionError("Snapshots must not read executable files"),
    )
    def test_snapshot_returns_stored_document_without_source_file(self, locate):
        response = self.client.get(self.url, {"digest": self.definition.digest})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), self.document)
        self.assertEqual(response["Content-Type"], "application/json")
        locate.assert_not_called()

    def test_changed_file_does_not_replace_selected_snapshot(self):
        with TemporaryDirectory() as directory:
            source = Path(directory, "example.json")
            source.write_text('{"description":"New executable definition","steps":[]}')
            with patch(
                "qc_tool.frontend.dashboard.views.products.data.locate_product_definition",
                return_value=source,
            ) as locate:
                stored = self.client.get(self.url, {"digest": self.definition.digest})
                locate.assert_not_called()
                current = self.client.get(self.url)
                current_document = json.loads(b"".join(current.streaming_content))

        self.assertEqual(stored.json(), self.document)
        self.assertEqual(current_document["description"], "New executable definition")
        locate.assert_called_once_with("example")

    @patch(
        "qc_tool.frontend.dashboard.views.products.data.locate_product_definition",
        side_effect=AssertionError("Invalid revisions must never fall back to files"),
    )
    def test_unknown_malformed_and_ambiguous_digests_return_404(self, locate):
        for digest in ("", "a" * 63, "A" * 64, "z" * 64, "0" * 64):
            with self.subTest(digest=digest):
                response = self.client.get(self.url, {"digest": digest})
                self.assertEqual(response.status_code, 404)
        response = self.client.get(
            self.url,
            {"digest": [self.definition.digest, "0" * 64]},
        )
        self.assertEqual(response.status_code, 404)
        locate.assert_not_called()

    def test_digest_is_scoped_to_the_requested_definition_identifier(self):
        response = self.client.get(
            reverse("product_definition_json", args=("different",)),
            {"digest": self.definition.digest},
        )

        self.assertEqual(response.status_code, 404)

    def test_snapshot_route_requires_login(self):
        self.client.logout()

        response = self.client.get(self.url, {"digest": self.definition.digest})

        self.assertEqual(response.status_code, 401)

    def test_managed_detail_links_each_exact_stored_definition(self):
        UserProductGrant.objects.create(user=self.user, product_ident="business")
        product = Product.objects.create(ident="business", name="Business product")
        release = ProductRelease.objects.create(
            product=product,
            release_key="business-2024",
            revision=1,
            description="Reviewed release",
            catalog_digest="a" * 64,
            coverage_state=ProductRelease.CoverageState.UNKNOWN,
            is_current=True,
        )
        additional = QcDefinition.objects.create(
            product_ident="additional",
            digest="b" * 64,
            description="Additional definition",
            document={"description": "Additional definition", "steps": []},
            source_path="/unavailable/additional.json",
        )
        for definition in (self.definition, additional):
            ProductReleaseDefinition.objects.create(
                product_release=release,
                qc_definition=definition,
                is_primary=definition == self.definition,
            )

        response = self.client.get(reverse("product_detail", args=(product.ident,)))

        self.assertEqual(response.status_code, 200)
        for definition in (self.definition, additional):
            url = reverse("product_definition_json", args=(definition.product_ident,))
            self.assertContains(response, '{}?digest={}'.format(url, definition.digest))
            self.assertContains(response, definition.digest[:12])
