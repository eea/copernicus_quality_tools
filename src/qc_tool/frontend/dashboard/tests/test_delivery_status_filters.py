"""Backend contracts for the deliveries workspace status filters."""

import io
import json

import openpyxl
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
from qc_tool.frontend.accounts.models import UserProductGrant
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
        UserProductGrant.objects.create(user=self.user, product_ident="test_product")
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
            "attention": len(all_visible) - 1,
            "not_validated": 1,
            "running": 2,
            "passed": 1,
            "failed": 7,
            "submitted": 1,
            "accepted": 0,
            "needs_correction": 0,
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
                "attention": 2,
                "not_validated": 0,
                "running": 0,
                "passed": 1,
                "failed": 1,
                "submitted": 0,
                "accepted": 0,
                "needs_correction": 0,
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
                "attention": 2,
                "not_validated": 0,
                "running": 0,
                "passed": 1,
                "failed": 1,
                "submitted": 0,
                "accepted": 0,
                "needs_correction": 0,
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
        account_access.operable_product_idents

        with self.assertNumQueries(1):
            counts = count_delivery_statuses(account_access)

        self.assertEqual(
            counts.as_dict(),
            {
                "all": 12,
                "attention": 11,
                "not_validated": 1,
                "running": 2,
                "passed": 1,
                "failed": 7,
                "submitted": 1,
                "accepted": 0,
                "needs_correction": 0,
            },
        )

    def test_default_view_excludes_submitted_and_orders_work_before_pagination(self):
        self.create_status_matrix()
        response = self.client.get(reverse("deliveries_json"), {"limit": 100}).json()
        self.assertEqual(response["active_status"], "all")
        self.assertEqual(response["active_view"], "action_required")
        self.assertEqual(response["total"], 9)
        self.assertEqual(response["status_counts"]["attention"], 11)
        self.assertNotIn("submitted.zip", [row["filename"] for row in response["rows"]])
        self.assertEqual([row["delivery_status"] for row in response["rows"]],
                         ["failed"] * 7 + ["not_validated", "passed"])
        first = self.client.get(reverse("deliveries_json"), {"limit": 3, "offset": 0}).json()
        second = self.client.get(reverse("deliveries_json"), {"limit": 3, "offset": 3}).json()
        self.assertEqual([row["id"] for row in first["rows"] + second["rows"]], [row["id"] for row in response["rows"][:6]])
        newest = self.client.get(reverse("deliveries_json"), {"sort": "id", "order": "desc", "limit": 100}).json()
        self.assertEqual([row["id"] for row in newest["rows"]], [row["id"] for row in response["rows"]])
        submitted = self.client.get(reverse("deliveries_json"), {"delivery_status": "submitted"}).json()
        self.assertEqual([row["filename"] for row in submitted["rows"]], ["submitted.zip"])

    def test_workflow_views_are_exclusive_with_counts_before_secondary_status(self):
        self.create_status_matrix()
        expected = {"action_required": 9, "running": 2, "in_review": 1, "completed": 0, "all": 12}
        ids = set()
        for view, count in expected.items():
            with self.subTest(view=view):
                payload = self.client.get(reverse("deliveries_json"), {
                    "delivery_view": view, "limit": 100,
                }).json()
                self.assertEqual(payload["active_view"], view)
                self.assertEqual(payload["workflow_counts"], expected)
                self.assertEqual(payload["total"], count)
                if view != "all":
                    current = {row["id"] for row in payload["rows"]}
                    self.assertFalse(ids & current)
                    ids.update(current)
                    self.assertTrue(all(row["workflow_stage"] == view for row in payload["rows"]))
        self.assertEqual(len(ids), expected["all"])
        payload = self.client.get(reverse("deliveries_json"), {
            "delivery_view": "action_required", "delivery_status": "passed",
        }).json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["workflow_counts"], expected)
        # A conflicting secondary state cannot broaden its parent view.
        self.assertEqual(self.client.get(reverse("deliveries_json"), {
            "delivery_view": "completed", "delivery_status": "failed",
        }).json()["total"], 0)

    def test_qc_completion_moves_delivery_from_running_to_its_next_action(self):
        delivery = self.create_delivery("processing.zip", status=JOB_WAITING)
        job = Job.objects.get(delivery=delivery)
        for state, expected_view, expected_status in (
            (JOB_WAITING, "running", "running"),
            (JOB_RUNNING, "running", "running"),
            (JOB_FAILED, "action_required", "failed"),
            (JOB_OK, "action_required", "passed"),
        ):
            with self.subTest(state=state):
                job.job_status = state
                job.save(update_fields=["job_status"])
                payload = self.client.get(reverse("deliveries_json"), {
                    "delivery_view": expected_view,
                }).json()
                self.assertEqual(payload["total"], 1)
                self.assertEqual(payload["rows"][0]["delivery_status"], expected_status)
                self.assertEqual(payload["workflow_counts"][expected_view], 1)
                other_view = "running" if expected_view == "action_required" else "action_required"
                self.assertEqual(payload["workflow_counts"][other_view], 0)

    def test_action_group_priority_precedes_column_sort_and_matches_excel(self):
        self.create_delivery("a-passed.zip", status=JOB_OK)
        self.create_delivery("b-unvalidated.zip")
        self.create_delivery("z-failure.zip", status=JOB_FAILED)
        self.create_delivery("c-failure.zip", status=JOB_FAILED)
        parameters = {"delivery_view": "action_required", "sort": "filename", "order": "asc"}
        response = self.client.get(reverse("deliveries_json"), parameters).json()
        expected = ["c-failure.zip", "z-failure.zip", "b-unvalidated.zip", "a-passed.zip"]
        self.assertEqual([row["filename"] for row in response["rows"]], expected)
        exported = self.client.get(reverse("export_deliveries_excel"), parameters)
        self.assertEqual(exported.status_code, 200)
        workbook = openpyxl.load_workbook(io.BytesIO(b"".join(exported.streaming_content)), read_only=True)
        rows = list(workbook.active.values)
        filename_column = rows[0].index("Delivery")
        self.assertEqual([row[filename_column] for row in rows[1:]], expected)
        workbook.close()

    def test_invalid_workflow_is_rejected_by_json_and_excel(self):
        self.create_delivery("owned.zip")
        query = {"delivery_view": "completed' OR 1=1 --"}
        response = self.client.get(reverse("deliveries_json"), query)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_delivery_view")
        self.assertEqual(self.client.get(reverse("export_deliveries_excel"), query).status_code, 400)
