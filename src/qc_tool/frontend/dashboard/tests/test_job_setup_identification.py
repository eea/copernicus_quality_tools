"""Filename hints guide QC choices without becoming verified delivery data."""

from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from qc_tool.delivery_names import DeliveryNameParserUnavailable
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.tests.catalog_fixtures import managed_definition


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class JobSetupIdentificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="filename-hints-owner")
        for ident in ("product-a", "product-b", "product-c"):
            managed_definition(ident)
        for ident in ("product-a", "product-b"):
            UserProductGrant.objects.create(user=cls.user, product_ident=ident)
        cls.delivery = Delivery.objects.create(
            user=cls.user, filename="first.zip", size_bytes=1,
            product_ident="product-a", product_unit_code="verified-unit",
        )
        cls.second = Delivery.objects.create(
            user=cls.user, filename="second.zip", size_bytes=1,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def result(self, status, candidates=(), *, summary="Urban Atlas · 2024 · Example city"):
        return SimpleNamespace(
            status=status, candidates=candidates, summary=summary,
            product_ident=candidates[0] if len(candidates) == 1 else None,
            parsed=SimpleNamespace(status="unsupported" if status == "unknown" else "recognized"),
            message="Review the filename before continuing." if status in {"invalid", "unconfigured"} else "",
        )

    def page(self, results, *, deliveries=None):
        def preview(result, _access):
            return {
                "status": result.status, "parsed_status": result.parsed.status,
                "summary": result.summary, "message": result.message,
            }
        with patch(
            "qc_tool.frontend.dashboard.views.jobs.setup.identify_delivery",
            side_effect=results,
        ), patch(
            "qc_tool.frontend.dashboard.views.jobs.setup.identification_preview",
            side_effect=preview,
        ):
            return self.client.get(reverse("setup_job"), {
                "deliveries": ",".join(str(item.pk) for item in (deliveries or (self.delivery,))),
            })

    @staticmethod
    def choices(response):
        return {option["product_ident"] for option in response.context["product_list"]}

    def test_unique_match_preselects_current_specification_without_rewriting_delivery(self):
        response = self.page([self.result("matched", ("product-b",))])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.choices(response), {"product-b"})
        self.assertEqual(response.context["product_ident"], "product-b")
        self.assertContains(response, "Filename details")
        self.assertContains(response, "QC verifies the delivery contents and product unit")
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.product_ident, "product-a")
        self.assertEqual(self.delivery.product_unit_code, "verified-unit")

    def test_ambiguous_match_keeps_only_assigned_candidates_and_requires_a_choice(self):
        response = self.page([self.result("ambiguous", ("product-a", "product-b", "product-c"))])

        self.assertEqual(self.choices(response), {"product-a", "product-b"})
        self.assertIsNone(response.context["product_ident"])
        self.assertFalse(response.context["identification_blocks_jobs"])
        self.assertContains(response, "Choose the correct specification")
        self.assertNotContains(response, 'value="product-c"')

    def test_invalid_and_unconfigured_names_disable_qc_with_an_explanation(self):
        for status in ("invalid", "unconfigured"):
            with self.subTest(status=status):
                response = self.page([self.result(status)])
                self.assertFalse(self.choices(response))
                self.assertTrue(response.context["identification_blocks_jobs"])
                self.assertContains(response, "Review the filename before continuing.")
                self.assertContains(response, "<fieldset disabled>", html=False)

    def test_different_recognized_products_cannot_be_run_as_one_batch(self):
        response = self.page([
            self.result("matched", ("product-a",)),
            self.result("matched", ("product-b",)),
        ], deliveries=(self.delivery, self.second))

        self.assertFalse(self.choices(response))
        self.assertTrue(response.context["identification_blocks_jobs"])
        self.assertContains(response, "Start separate QC jobs for these products.")

    def test_unknown_legacy_filename_retains_assigned_choices_and_recorded_selection(self):
        response = self.page([self.result("unknown", summary="")])

        self.assertEqual(self.choices(response), {"product-a", "product-b"})
        self.assertEqual(response.context["product_ident"], "product-a")
        self.assertFalse(response.context["identification_blocks_jobs"])
        self.assertNotContains(response, "Filename details are hints")

    def test_displayed_hints_are_html_escaped(self):
        response = self.page([self.result(
            "matched", ("product-b",), summary='<script>alert("filename")</script>',
        )])

        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, '<script>alert("filename")</script>')

    def test_parser_outage_keeps_the_page_available_with_qc_disabled(self):
        with patch(
            "qc_tool.frontend.dashboard.views.jobs.setup.identify_delivery",
            side_effect=DeliveryNameParserUnavailable("Internal parser configuration details"),
        ):
            response = self.client.get(reverse("setup_job"), {"deliveries": str(self.delivery.pk)})

        self.assertContains(response, "Delivery filename recognition is temporarily unavailable", status_code=503)
        self.assertContains(response, self.delivery.filename, status_code=503)
        self.assertContains(response, "<fieldset disabled>", status_code=503)
        self.assertNotContains(response, "Internal parser configuration", status_code=503)
