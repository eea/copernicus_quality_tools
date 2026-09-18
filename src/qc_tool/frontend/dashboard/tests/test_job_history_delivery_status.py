"""QC history explains the delivery lifecycle and offers a safe first run."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from qc_tool.common import JOB_FAILED, JOB_OK, JOB_RUNNING, JOB_WAITING
from qc_tool.frontend.accounts.authorization import access_for
from qc_tool.frontend.accounts.authorization.permissions import AccountPermission
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import UserProductGrant, UserProfile, UserRegionGrant
from qc_tool.frontend.dashboard.models import (
    Delivery, DeliverySubmission, Job, Product, ProductAOI, ProductRelease,
)
from qc_tool.frontend.dashboard.services.jobs.presentation import job_history_delivery_summary


@override_settings(DEBUG=False, MAINTENANCE_MODE=False)
class JobHistoryDeliveryStatusTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user(username="history-state-owner")
        UserProductGrant.objects.create(user=cls.owner, product_ident="history-product")
        cls.administrator = get_user_model().objects.create_superuser(
            username="history-state-administrator", password="test-password",
        )
        cls.manager = get_user_model().objects.create_user(username="history-state-manager")
        cls.manager.groups.add(Group.objects.get(name=Role.PRODUCT_MANAGER.value))
        UserProductGrant.objects.create(user=cls.manager, product_ident="history-product")
        cls.product = Product.objects.create(ident="history-product", name="History product")
        cls.release = ProductRelease.objects.create(
            product=cls.product, release_key="history-v1", revision=1,
            catalog_digest="c" * 64, is_current=True,
        )
        cls.aoi = ProductAOI.objects.create(
            product_release=cls.release, aoi_code="CZ", provenance="manifest",
        )

    def setUp(self):
        self.delivery = Delivery.objects.create(
            user=self.owner, filename="history-state.zip", size_bytes=1024,
            product_ident=self.product.ident,
        )
        self.client.force_login(self.owner)
        self.json_url = reverse("job_history_json", args=(self.delivery.pk,))

    def summary(self, user=None, delivery=None):
        return job_history_delivery_summary(
            delivery or self.delivery, access_for(user or self.owner),
        )

    def create_job(self, status, *, delivery=None, **fields):
        fields.setdefault("product_ident", self.product.ident)
        return Job.objects.create(
            delivery=delivery or self.delivery, job_status=status, **fields,
        )

    def create_submission(self, job, *, review_state="pending", publication_state="published"):
        return DeliverySubmission.objects.create(
            delivery=job.delivery, job=job, product_release=self.release,
            product_aoi=self.aoi, aoi_code="CZ", aoi_code_submitted="CZ",
            submitted_by=self.owner, submitted_by_username=self.owner.username,
            request_channel="browser", review_state=review_state,
            publication_state=publication_state,
            published_at=timezone.now() if publication_state == "published" else None,
            artifact_path="/published/history.zip", artifact_digest="a" * 64,
            input_digest="b" * 64,
        )

    def test_no_runs_shows_not_validated_and_first_run_for_owner_and_admin(self):
        for user in (self.owner, self.administrator):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                response = self.client.get(reverse("job_history", args=(self.delivery.pk,)))
                self.assertEqual(response.status_code, 200)
                summary = response.context["delivery_summary"]
                self.assertEqual(summary["status_label"], "Delivery status")
                self.assertEqual(summary["status"], {
                    "value": "not_validated", "label": "Not validated", "tone": "neutral",
                })
                self.assertEqual(summary["action"], {
                    "label": "Run QC", "icon": "play",
                    "url": f"{reverse('setup_job')}?deliveries={self.delivery.pk}",
                })
                self.assertContains(response, "Delivery status")
                self.assertContains(response, "Not validated")
                self.assertContains(response, "Run QC")

    def test_latest_run_controls_status_and_removes_first_run_action(self):
        self.create_job(JOB_OK, date_created=timezone.now() - timedelta(days=1))
        cases = (
            (JOB_WAITING, "running", "In queue", "warning"),
            (JOB_RUNNING, "running", "In progress", "warning"),
            (JOB_OK, "passed", "Validated", "success"),
            (JOB_FAILED, "failed", "Failed", "danger"),
            ("worker timeout", "failed", "Failed", "danger"),
        )
        now = timezone.now()
        for index, (job_status, value, label, tone) in enumerate(cases):
            with self.subTest(job_status=job_status):
                self.create_job(job_status, date_created=now + timedelta(seconds=index))
                summary = self.summary()
                self.assertEqual(summary["status"], {"value": value, "label": label, "tone": tone})
                self.assertIsNone(summary["action"])

    def test_submitted_timestamp_takes_precedence_over_qc_state(self):
        self.create_job(JOB_OK)
        self.delivery.date_submitted = timezone.now()
        self.delivery.save(update_fields=("date_submitted",))

        summary = self.summary()

        self.assertEqual(summary["status"], {
            "value": "submitted", "label": "Submitted", "tone": "primary",
        })
        self.assertIsNone(summary["action"])

    def test_published_review_decision_takes_precedence_over_qc_result(self):
        job = self.create_job(JOB_OK)
        submission = self.create_submission(job)
        self.delivery.date_submitted = timezone.now()
        self.delivery.save(update_fields=("date_submitted",))
        for review_state, value, label, tone in (
            ("rejected", "needs_correction", "Correction needed", "warning"),
            ("accepted", "accepted", "Accepted", "success"),
            ("conflict", "submitted", "Submitted", "primary"),
        ):
            submission.review_state = review_state
            submission.save(update_fields=("review_state",))
            for user in (self.owner, self.manager, self.administrator):
                with self.subTest(review=review_state, viewer=user.username):
                    summary = self.summary(user)
                    self.assertEqual(summary["status"], {"value": value, "label": label, "tone": tone})
                    self.assertIsNone(summary["action"])

    def test_unpublished_review_is_not_presented_as_completed(self):
        self.create_submission(
            self.create_job(JOB_OK), review_state="accepted", publication_state="pending",
        )

        summary = self.summary()

        self.assertEqual(summary["status"]["value"], "passed")
        self.assertIsNone(summary["action"])

    def test_region_viewer_does_not_see_private_review_status(self):
        self.create_submission(self.create_job(JOB_OK), review_state="rejected")
        self.delivery.date_submitted = timezone.now()
        self.delivery.save(update_fields=("date_submitted",))
        viewer = get_user_model().objects.create_user(username="history-state-region-viewer")
        UserProfile.objects.create(user=self.owner, country="CZ")
        UserRegionGrant.objects.create(user=viewer, aoi_code="CZ")
        viewer.user_permissions.add(Permission.objects.get(
            content_type__app_label="accounts", codename="view_region_deliveries",
        ))
        self.client.force_login(viewer)

        response = self.client.get(self.json_url, {"include_delivery": "1"})

        self.assertEqual(response.status_code, 200)
        summary = response.json()["delivery_summary"]
        self.assertEqual(summary["status"]["label"], "Submitted")
        self.assertIsNone(summary["action"])

    def test_first_run_requires_both_owner_management_and_run_permission(self):
        self.assertIsNone(self.summary(self.manager)["action"])
        access = access_for(self.owner)
        access = replace(access, permissions=access.permissions - {AccountPermission.RUN_QC})

        summary = job_history_delivery_summary(self.delivery, access)

        self.assertIsNone(summary["action"])

    def test_deleted_or_submitted_delivery_never_offers_first_run(self):
        for field, value in (("is_deleted", True), ("date_submitted", timezone.now())):
            with self.subTest(field=field):
                self.delivery.refresh_from_db()
                setattr(self.delivery, field, value)
                self.assertIsNone(self.summary()["action"])

    def test_invisible_submission_reservation_still_blocks_first_run(self):
        # This defensive check is independent of receipt visibility or the
        # history projection: pending publication also reserves a delivery.
        with patch(
            "qc_tool.frontend.dashboard.services.jobs.presentation."
            "DeliverySubmission.objects.filter",
        ) as reservations:
            reservations.return_value.exists.return_value = True
            self.assertIsNone(self.summary()["action"])
            reservations.assert_any_call(delivery_id=self.delivery.pk)
            reservations.return_value.exists.assert_called_once_with()

    def test_envelope_is_opt_in_and_default_json_contract_is_preserved(self):
        job = self.create_job(JOB_OK)

        default = self.client.get(self.json_url)
        enriched = self.client.get(self.json_url, {"include_delivery": "1"})
        unrequested = self.client.get(self.json_url, {"include_delivery": "0"})

        self.assertIsInstance(default.json(), list)
        self.assertEqual(default.json(), unrequested.json())
        self.assertEqual(default.json(), enriched.json()["rows"])
        self.assertEqual(default.json()[0]["job_uuid"], str(job.pk))
        self.assertEqual(enriched.json()["delivery_summary"]["status"]["label"], "Validated")

    def test_empty_history_envelope_contains_action_but_no_rows(self):
        response = self.client.get(self.json_url, {"include_delivery": "1"})

        self.assertEqual(response.json()["rows"], [])
        self.assertEqual(response.json()["delivery_summary"]["action"]["label"], "Run QC")

    @patch(
        "qc_tool.frontend.dashboard.services.aoi.lifecycle.load_aoi_result_document",
        return_value={"aoi_code": "CZ", "status": "ok"},
    )
    @patch(
        "qc_tool.frontend.dashboard.views.jobs.history.check_running_job",
        return_value=JOB_OK,
    )
    def test_refresh_returns_completed_status_and_updated_delivery_facts(self, check_job, _load_result):
        UserProductGrant.objects.create(user=self.owner, product_ident="fresh-definition")
        job = self.create_job(
            JOB_RUNNING, product_ident="fresh-definition",
            product_description="Fresh QC product description",
        )

        response = self.client.get(self.json_url, {"include_delivery": "1"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["rows"][0]["job_status"], JOB_OK)
        self.assertEqual(payload["delivery_summary"]["status"]["label"], "Validated")
        self.assertEqual(payload["delivery_summary"]["description"], "Fresh QC product description")
        self.assertEqual(payload["delivery_summary"]["facts"][-1], {"label": "Expected AOI", "value": "cz"})
        self.assertIsNone(payload["delivery_summary"]["action"])
        self.assertEqual(check_job.call_args.args[0], str(job.pk))

    def test_envelope_does_not_bypass_delivery_access(self):
        unrelated = get_user_model().objects.create_user(username="history-state-unrelated")
        self.client.force_login(unrelated)

        response = self.client.get(self.json_url, {"include_delivery": "1"})

        self.assertEqual(response.status_code, 403)
