from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.dashboard.tests.catalog_fixtures import managed_definition


class BrowserJobCreationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="job-owner")
        UserProductGrant.objects.create(user=self.user, product_ident="product")
        self.client.force_login(self.user)
        definition = managed_definition("product")
        self.enterContext(patch(
            "qc_tool.frontend.dashboard.services.product_units.jobs.creation._catalog_snapshot",
            return_value=definition,
        ))
        self.deliveries = [
            Delivery.objects.create(
                user=self.user,
                filename="delivery-{}.zip".format(number),
                size_bytes=10,
            )
            for number in (1, 2)
        ]

    def _post(self, delivery_ids):
        return self.client.post(
            reverse("create_job"),
            {
                "delivery_ids": ",".join(
                    str(delivery_id) for delivery_id in delivery_ids
                ),
                "product_ident": "product",
                "skip_steps": "",
            },
        )

    def _definition_context(self):
        temporary = TemporaryDirectory()
        definition = Path(temporary.name).joinpath("product.json")
        definition.write_text('{"steps": []}', encoding="utf-8")
        return temporary, patch(
            "qc_tool.frontend.dashboard.services.jobs.requests.locate_product_definition",
            return_value=definition,
        )

    def test_creates_a_valid_owner_batch_atomically(self):
        temporary, definition = self._definition_context()
        with temporary, definition, patch(
            "qc_tool.frontend.dashboard.services.products.find_product_description",
            return_value="Product",
        ):
            response = self._post([delivery.pk for delivery in self.deliveries])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["num_created"], 2)
        self.assertEqual(Job.objects.count(), 2)

    def test_rejects_a_missing_delivery_before_creating_any_job(self):
        temporary, definition = self._definition_context()
        with temporary, definition:
            response = self._post([self.deliveries[0].pk, 999999])

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "delivery_not_found")
        self.assertFalse(Job.objects.exists())

    def test_rolls_back_the_whole_batch_when_creation_fails(self):
        original_create_job = Delivery.create_job
        calls = {"count": 0}

        def fail_second(delivery, product_ident, skip_steps, **kwargs):
            calls["count"] += 1
            if calls["count"] == 2:
                raise RuntimeError("simulated database-side failure")
            return original_create_job(delivery, product_ident, skip_steps, **kwargs)

        temporary, definition = self._definition_context()
        with temporary, definition, patch(
            "qc_tool.frontend.dashboard.services.products.find_product_description",
            return_value="Product",
        ), patch.object(Delivery, "create_job", new=fail_second):
            response = self._post([delivery.pk for delivery in self.deliveries])

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["code"], "job_creation_failed")
        self.assertFalse(Job.objects.exists())
        self.assertFalse(
            Delivery.objects.exclude(product_ident__isnull=True).exists()
        )
