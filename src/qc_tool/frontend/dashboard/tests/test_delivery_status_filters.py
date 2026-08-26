"""Backend contracts for the deliveries workspace status filters."""

import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from qc_tool.common import JOB_ERROR
from qc_tool.common import JOB_FAILED
from qc_tool.common import JOB_LOST
from qc_tool.common import JOB_OK
from qc_tool.common import JOB_PARTIAL
from qc_tool.common import JOB_RUNNING
from qc_tool.common import JOB_TIMEOUT
from qc_tool.common import JOB_WAITING
from qc_tool.frontend.accounts.authorization import access_for
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.dashboard.services.deliveries import (
    count_delivery_statuses,
)


FILE_NOT_FOUND_STATUS = "file_not_found"


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class DeliveryStatusFilterTests(TestCase):
    """Status tabs use the latest job and the requester's access scope."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="delivery-filter-user",
            password="test-password",
        )
        self.other_user = get_user_model().objects.create_user(
            username="hidden-delivery-filter-user",
            password="test-password",
        )
        self.client.force_login(self.user)
        self.now = timezone.now()

    def create_delivery(
        self,
        filename,
        *,
        status=None,
        submitted=False,
        user=None,
        created_at=None,
        product_description="Test product",
        aoi_code="test-aoi",
    ):
        delivery = Delivery.objects.create(
            user=user or self.user,
            filename=filename,
            size_bytes=1024,
            date_submitted=self.now if submitted else None,
            product_ident="TEST_PRODUCT",
            product_description=product_description,
            aoi_code=aoi_code,
        )
        if status is not None:
            Job.objects.create(
                delivery=delivery,
                date_created=created_at or self.now,
                job_status=status,
                product_ident="TEST_PRODUCT",
                product_description="Test product",
                aoi_code="test-aoi",
            )
        return delivery

    def create_status_matrix(self):
        not_validated = self.create_delivery("not-validated.zip")
        waiting = self.create_delivery("waiting.zip", status=JOB_WAITING)
        running = self.create_delivery("running.zip", status=JOB_RUNNING)

        passed = self.create_delivery("passed.zip")
        Job.objects.create(
            delivery=passed,
            date_created=self.now - timedelta(minutes=1),
            job_status=JOB_FAILED,
            product_ident="TEST_PRODUCT",
            product_description="Test product",
        )
        passed_job = Job.objects.create(
            delivery=passed,
            date_created=self.now,
            job_status=JOB_OK,
            product_ident="TEST_PRODUCT",
            product_description="Test product",
        )

        failed = {
            self.create_delivery("partial.zip", status=JOB_PARTIAL),
            self.create_delivery("failed.zip", status=JOB_FAILED),
            self.create_delivery("error.zip", status=JOB_ERROR),
            self.create_delivery("timeout.zip", status=JOB_TIMEOUT),
            self.create_delivery("lost.zip", status=JOB_LOST),
            self.create_delivery(
                "file-not-found.zip",
                status=FILE_NOT_FOUND_STATUS,
            ),
            # Unknown terminal states must fail closed into the attention
            # bucket instead of silently disappearing from the public tabs.
            self.create_delivery("unknown-status.zip", status="legacy-state"),
        }
        # Submitted is a delivery lifecycle state and therefore takes
        # precedence even if a legacy row has an unexpected latest job status.
        submitted = self.create_delivery(
            "submitted.zip",
            status=JOB_FAILED,
            submitted=True,
        )
        hidden = self.create_delivery(
            "hidden.zip",
            status=JOB_OK,
            user=self.other_user,
        )
        return {
            "not_validated": {not_validated},
            "running": {waiting, running},
            "passed": {passed},
            "failed": failed,
            "submitted": {submitted},
            "hidden": {hidden},
            "passed_job": passed_job,
        }

    def test_json_filters_are_mutually_exclusive_and_access_scoped(self):
        matrix = self.create_status_matrix()
        expected_by_status = {
            status: {delivery.filename for delivery in deliveries}
            for status, deliveries in matrix.items()
            if status
            in {"not_validated", "running", "passed", "failed", "submitted"}
        }
        all_visible = set().union(*expected_by_status.values())
        expected_counts = {
            "all": len(all_visible),
            "not_validated": 1,
            "running": 2,
            "passed": 1,
            "failed": 7,
            "submitted": 1,
        }

        for status, expected_filenames in (
            ("all", all_visible),
            *expected_by_status.items(),
        ):
            with self.subTest(status=status):
                response = self.client.get(
                    reverse("deliveries_json"),
                    {"delivery_status": status, "limit": 100},
                )

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["active_status"], status)
                self.assertEqual(payload["status_counts"], expected_counts)
                self.assertEqual(payload["total"], len(expected_filenames))
                self.assertEqual(
                    {row["filename"] for row in payload["rows"]},
                    expected_filenames,
                )
                if status != "all":
                    self.assertEqual(
                        {row["delivery_status"] for row in payload["rows"]},
                        {status},
                    )
                self.assertNotIn(
                    "hidden.zip",
                    {row["filename"] for row in payload["rows"]},
                )

        all_response = self.client.get(
            reverse("deliveries_json"),
            {"delivery_status": "all", "limit": 100},
        ).json()
        rows_by_filename = {
            row["filename"]: row for row in all_response["rows"]
        }
        self.assertEqual(
            rows_by_filename["passed.zip"]["last_job_uuid"],
            str(matrix["passed_job"].job_uuid),
        )
        self.assertEqual(
            rows_by_filename["passed.zip"]["job_history_url"],
            reverse(
                "job_history",
                args=(next(iter(matrix["passed"])).pk,),
            ),
        )
        self.assertEqual(
            rows_by_filename["passed.zip"]["job_result_url"],
            reverse("show_result", args=(matrix["passed_job"].job_uuid,)),
        )
        self.assertIsNone(
            rows_by_filename["not-validated.zip"]["job_result_url"]
        )

    def test_invalid_status_is_rejected_instead_of_broadening_results(self):
        self.create_delivery("owned.zip")

        response = self.client.get(
            reverse("deliveries_json"),
            {"delivery_status": "passed' OR 1=1 --"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_delivery_status")

    def test_counts_follow_text_product_and_aoi_filters_before_status(self):
        self.create_delivery(
            "matching-passed.zip",
            status=JOB_OK,
            product_description="Target product",
            aoi_code="target-aoi",
        )
        self.create_delivery(
            "matching-failed.zip",
            status=JOB_FAILED,
            product_description="Target product",
            aoi_code="target-aoi",
        )
        self.create_delivery(
            "outside.zip",
            status=JOB_OK,
            product_description="Other product",
            aoi_code="other-aoi",
        )

        search_response = self.client.get(
            reverse("deliveries_json"),
            {
                "delivery_status": "passed",
                "search": "matching-",
                "limit": 100,
            },
        )

        self.assertEqual(search_response.status_code, 200)
        self.assertEqual(search_response.json()["total"], 1)
        self.assertEqual(
            search_response.json()["status_counts"],
            {
                "all": 2,
                "not_validated": 0,
                "running": 0,
                "passed": 1,
                "failed": 1,
                "submitted": 0,
            },
        )

        field_response = self.client.get(
            reverse("deliveries_json"),
            {
                "delivery_status": "all",
                "filter": json.dumps(
                    {
                        "product_description": "Target product",
                        "aoi_code": "target-aoi",
                    }
                ),
                "limit": 100,
            },
        )

        self.assertEqual(field_response.status_code, 200)
        self.assertEqual(
            field_response.json()["status_counts"],
            {
                "all": 2,
                "not_validated": 0,
                "running": 0,
                "passed": 1,
                "failed": 1,
                "submitted": 0,
            },
        )

    def test_non_string_legacy_filters_are_ignored_without_server_error(self):
        self.create_delivery("owned.zip", status=JOB_OK)

        response = self.client.get(
            reverse("deliveries_json"),
            {
                "filter": json.dumps(
                    {
                        "product_description": [],
                        "aoi_code": {"unexpected": "shape"},
                    }
                )
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.json()["status_counts"]["all"], 1)

    def test_status_counts_use_one_query_and_submitted_first_precedence(self):
        self.create_status_matrix()
        account_access = access_for(self.user)

        with self.assertNumQueries(1):
            counts = count_delivery_statuses(account_access)

        self.assertEqual(
            counts.as_dict(),
            {
                "all": 12,
                "not_validated": 1,
                "running": 2,
                "passed": 1,
                "failed": 7,
                "submitted": 1,
            },
        )
