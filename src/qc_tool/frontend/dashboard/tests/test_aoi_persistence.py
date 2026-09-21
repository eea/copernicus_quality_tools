from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import TestCase
from django.utils import timezone

from qc_tool.common import JOB_FAILED
from qc_tool.common import JOB_ERROR
from qc_tool.common import JOB_OK
from qc_tool.common import JOB_RUNNING
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.dashboard.services.product_units import (
    apply_result_product_unit, refresh_delivery_projection,
)
from qc_tool.frontend.accounts.models import PersonalAccessToken
from qc_tool.frontend.dashboard.services.product_units import ProductUnitResultUnavailable
from qc_tool.frontend.dashboard.services.jobs import serialize_job_history
from qc_tool.frontend.dashboard.services.jobs import serialize_job_report
from qc_tool.frontend.dashboard.services.deliveries.listing import query_deliveries
from qc_tool.frontend.dashboard.tests.catalog_fixtures import managed_definition


class ProductUnitPersistenceTests(TestCase):
    def setUp(self):
        definitions = {ident: managed_definition(ident) for ident in ("product", "new-product")}
        self.enterContext(patch(
            "qc_tool.frontend.dashboard.services.product_units.jobs.creation._catalog_snapshot",
            side_effect=lambda ident, **kwargs: definitions[ident],
        ))
        self.user = get_user_model().objects.create_user(
            username="aoi-owner",
            password="test-password",
        )
        self.delivery = Delivery.objects.create(
            user=self.user,
            filename="delivery.zip",
            size_bytes=1024,
        )

    def create_job(self, *, created_at=None, product_unit_code=None, job_uuid=None):
        values = {
            "delivery": self.delivery,
            "date_created": created_at or timezone.now(),
            "job_status": JOB_RUNNING,
            "product_ident": "product",
            "product_description": "Product",
            "product_unit_code": product_unit_code,
        }
        if job_uuid is not None:
            values["job_uuid"] = job_uuid
        return Job.objects.create(**values)

    @patch(
        "qc_tool.frontend.dashboard.services.product_units.lifecycle."
        "load_product_unit_result_document",
        return_value={"aoi_code": "EE003LX"},
    )
    def test_terminal_result_updates_job_and_delivery_canonically(self, loader):
        job = self.create_job()

        job.update_status(JOB_OK)
        job.refresh_from_db()
        self.delivery.refresh_from_db()

        loader.assert_called_once_with(job.job_uuid)
        self.assertEqual(job.product_unit_code, "ee003l")
        self.assertEqual(job.verified_product_unit_code, "ee003l")
        self.assertEqual(self.delivery.product_unit_code, "ee003l")
        self.assertEqual(self.delivery.verified_product_unit_code, "ee003l")
        self.assertIsNotNone(job.date_finished)

    @patch(
        "qc_tool.frontend.dashboard.services.product_units.lifecycle."
        "load_product_unit_result_document",
        return_value={"status": "ok"},
    )
    def test_success_without_one_verified_aoi_becomes_job_error(self, _):
        job = self.create_job()

        with self.assertLogs(
            "qc_tool.frontend.dashboard.services.product_units.lifecycle",
            level="ERROR",
        ):
            job.update_status(JOB_OK)
        job.refresh_from_db()

        self.assertEqual(job.job_status, JOB_ERROR)
        self.assertIsNone(job.verified_product_unit_code)

    @patch(
        "qc_tool.frontend.dashboard.services.product_units.lifecycle."
        "load_product_unit_result_document",
        return_value={"product_unit_code": "007", "aoi_code": "007"},
    )
    def test_conflicting_result_aliases_preserve_identity_and_reject_success(self, _):
        job = self.create_job(product_unit_code="existing")
        job.verified_product_unit_code = "existing"
        job.save(update_fields=("verified_product_unit_code",))
        with self.assertLogs(
            "qc_tool.frontend.dashboard.services.product_units.lifecycle", level="ERROR",
        ):
            job.update_status(JOB_OK)
        job.refresh_from_db()
        self.assertEqual(job.job_status, JOB_ERROR)
        self.assertEqual(job.product_unit_code, "existing")
        self.assertEqual(job.verified_product_unit_code, "existing")

    @patch(
        "qc_tool.frontend.dashboard.services.product_units.lifecycle."
        "load_product_unit_result_document",
        return_value={"product_unit_code": "007"},
    )
    def test_new_opaque_result_identity_is_projected_without_removing_padding(self, _):
        job = self.create_job()
        job.update_status(JOB_OK)
        job.refresh_from_db()
        self.delivery.refresh_from_db()
        self.assertEqual(job.job_status, JOB_OK)
        self.assertEqual(job.verified_product_unit_code, "007")
        self.assertEqual(self.delivery.verified_product_unit_code, "007")

    @patch(
        "qc_tool.frontend.dashboard.services.product_units.lifecycle."
        "load_product_unit_result_document",
        return_value={"aoi_code": "EE002L1"},
    )
    def test_later_job_cannot_replace_the_zip_unit_identity(self, _):
        self.delivery.verified_product_unit_code = "ee001l"
        self.delivery.save(update_fields=("verified_product_unit_code",))
        job = self.create_job()

        with self.assertLogs(
            "qc_tool.frontend.dashboard.services.product_units.lifecycle",
            level="ERROR",
        ):
            job.update_status(JOB_OK)
        job.refresh_from_db()
        self.delivery.refresh_from_db()

        self.assertEqual(job.job_status, JOB_ERROR)
        self.assertEqual(job.verified_product_unit_code, "ee002l")
        self.assertEqual(self.delivery.verified_product_unit_code, "ee001l")

    @patch(
        "qc_tool.frontend.dashboard.services.product_units.lifecycle."
        "load_product_unit_result_document"
    )
    def test_running_status_does_not_read_result_metadata(self, loader):
        job = self.create_job(product_unit_code="existing")

        job.update_status(JOB_RUNNING)
        job.refresh_from_db()

        loader.assert_not_called()
        self.assertEqual(job.product_unit_code, "existing")
        self.assertIsNone(job.date_finished)

    @patch(
        "qc_tool.frontend.dashboard.services.product_units.lifecycle."
        "load_product_unit_result_document",
        return_value={"aoi_code": "EE003L1", "hash": "a" * 64, "reference_year": "2024"},
    )
    def test_terminal_job_metadata_cannot_be_replaced(self, loader):
        job = self.create_job()
        job.update_status(JOB_OK)
        job.refresh_from_db()
        original_finished = job.date_finished

        with self.assertLogs(
            "qc_tool.frontend.dashboard.services.product_units.lifecycle",
            level="WARNING",
        ):
            job.update_status(JOB_FAILED)
        job.refresh_from_db()

        self.assertEqual(job.job_status, JOB_OK)
        self.assertEqual(job.verified_product_unit_code, "ee003l")
        self.assertEqual(job.input_sha256, "a" * 64)
        self.assertEqual(job.date_finished, original_finished)
        self.assertEqual(job.reference_period, "2024")
        loader.assert_called_once_with(job.job_uuid)

    @patch(
        "qc_tool.frontend.dashboard.services.product_units.lifecycle."
        "load_product_unit_result_document",
        side_effect=ProductUnitResultUnavailable,
    )
    def test_unavailable_result_does_not_block_terminal_status(self, _):
        job = self.create_job(product_unit_code="existing")

        with self.assertLogs(
            "qc_tool.frontend.dashboard.services.product_units.lifecycle",
            level="WARNING",
        ):
            job.update_status(JOB_FAILED)
        job.refresh_from_db()

        self.assertEqual(job.job_status, JOB_FAILED)
        self.assertEqual(job.product_unit_code, "existing")
        self.assertIsNotNone(job.date_finished)

    def test_result_update_distinguishes_missing_null_and_malformed(self):
        job = self.create_job(product_unit_code="existing")

        self.assertEqual(apply_result_product_unit(job, {}), [])
        self.assertEqual(job.product_unit_code, "existing")
        self.assertEqual(apply_result_product_unit(job, {"product_unit_code": 123}), [])
        self.assertEqual(job.product_unit_code, "existing")
        self.assertEqual(
            apply_result_product_unit(job, {"product_unit_code": None}),
            ["product_unit_code"],
        )
        self.assertIsNone(job.product_unit_code)
        self.assertEqual(
            apply_result_product_unit(job, {"aoi_code": "EE003L1"}),
            ["product_unit_code", "verified_product_unit_code"],
        )
        self.assertEqual(job.product_unit_code, "ee003l")
        self.assertEqual(job.verified_product_unit_code, "ee003l")

    @patch(
        "qc_tool.frontend.dashboard.services.products.find_product_description",
        return_value="New product",
    )
    def test_newer_job_resets_delivery_projection_until_result_exists(self, _):
        older = self.create_job(product_unit_code="old-aoi")
        older.job_status = JOB_OK
        older.save(update_fields=("job_status",))
        refresh_delivery_projection(self.delivery)

        self.delivery.create_job("new-product", "")
        self.delivery.refresh_from_db()

        self.assertEqual(older.product_unit_code, "old-aoi")
        self.assertIsNone(self.delivery.product_unit_code)
        self.assertEqual(self.delivery.product_ident, "new-product")

    @patch(
        "qc_tool.frontend.dashboard.services.products.find_product_description",
        return_value="Product",
    )
    def test_token_deletion_does_not_rewrite_job_provenance(self, _):
        token = PersonalAccessToken.objects.create(
            user=self.user,
            name="QC request token",
            secret_digest="sha256$" + ("b" * 64),
        )
        token_id = token.pk

        self.delivery.create_job(
            "product",
            "",
            requested_by=self.user,
            request_source="api",
            api_token=token,
        )
        token.delete()

        job = Job.objects.get(delivery=self.delivery)
        self.assertEqual(job.requested_by_id, self.user.pk)
        self.assertEqual(job.requested_by_username, self.user.username)
        self.assertEqual(job.request_source, "api")
        self.assertEqual(job.requested_api_token_id, token_id)
        self.assertEqual(job.requested_api_token_name, "QC request token")

    @patch(
        "qc_tool.frontend.dashboard.services.product_units.lifecycle."
        "load_product_unit_result_document",
        return_value={"product_unit_code": "old-finished"},
    )
    def test_older_job_finishing_cannot_overwrite_newer_projection(self, _):
        now = timezone.now()
        older = self.create_job(created_at=now - timedelta(hours=1))
        self.create_job(created_at=now, product_unit_code="newer")
        refresh_delivery_projection(self.delivery)

        older.update_status(JOB_FAILED)
        self.delivery.refresh_from_db()

        self.assertEqual(self.delivery.product_unit_code, "newer")

    def test_projection_uses_uuid_as_tie_breaker_for_equal_timestamps(self):
        created_at = timezone.now()
        self.create_job(
            created_at=created_at,
            product_unit_code="lower-uuid",
            job_uuid=UUID(int=1),
        )
        self.create_job(
            created_at=created_at,
            product_unit_code="higher-uuid",
            job_uuid=UUID(int=2),
        )

        refresh_delivery_projection(self.delivery)
        self.delivery.refresh_from_db()

        self.assertEqual(self.delivery.product_unit_code, "higher-uuid")

    def test_serializers_expose_only_persisted_canonical_key(self):
        job = self.create_job(product_unit_code="canonical")
        job.verified_product_unit_code = "zip-canonical"

        history = serialize_job_history([job])[0]
        report = serialize_job_report(
            {
                "product_unit_code": "stale", "fua_code": "alias",
                "verified_product_unit_code": "forged-new",
                "submitted_product_unit_code": "forged-old",
                "qc_tool_version": "artifact-version",
            },
            job,
        )

        self.assertEqual(history["product_unit_code"], "canonical")
        self.assertEqual(history["verified_product_unit_code"], "zip-canonical")
        self.assertEqual(report["product_unit_code"], "canonical")
        self.assertEqual(report["verified_product_unit_code"], "zip-canonical")
        self.assertNotIn("fua_code", history)
        self.assertNotIn("fua_code", report)
        self.assertNotIn("submitted_product_unit_code", report)
        self.assertEqual(report["qc_tool_version"], "artifact-version")

    def test_delivery_list_projection_includes_aoi_for_every_row(self):
        self.delivery.product_unit_code = "ee003l"
        self.delivery.save(update_fields=("product_unit_code",))

        total, rows = query_deliveries(
            self.user,
            limit=10,
            account_access=SimpleNamespace(is_administrator=True),
        )

        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["product_unit_code"], "ee003l")

    def test_result_page_escapes_verified_unit_metadata(self):
        markup = '<img src=x onerror="alert(1)">'

        rendered = render_to_string(
            "dashboard/jobs/result.html",
            {
                "delivery": self.delivery,
                "job_report": {
                    "verified_product_unit_code": markup,
                    "job_uuid": UUID(int=1),
                    "steps": [],
                },
            },
        )

        self.assertNotIn(markup, rendered)
        self.assertIn("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;", rendered)
