"""Exercise plan activation, owner tracking, review and retained downloads."""

from pathlib import Path
import shutil
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.dashboard.models import DeliverySubmission, ProductRelease
from qc_tool.frontend.dashboard.services.catalog import get_product_coverage
from qc_tool.frontend.dashboard.services.submissions import SubmissionError
from qc_tool.frontend.dashboard.services.tests.test_submissions import SubmissionFixtureMixin


class SubmissionWorkspaceFixtureMixin(SubmissionFixtureMixin):
    def setUp(self):
        super().setUp()
        users = get_user_model().objects
        self.admin = users.create_superuser("review-admin", password="password")
        self.manager = users.create_user("assigned-manager", password="password")
        self.manager.groups.add(Group.objects.get(name="product_manager"))
        self.unassigned = users.create_user("unassigned-manager", password="password")
        self.unassigned.groups.add(Group.objects.get(name="product_manager"))
        UserProductGrant.objects.create(user=self.manager, product_ident=self.product.ident)
        self.owner, self.delivery, self.job, self.job_root = self.create_candidate("workspace-owner")
        self.storage = patch.dict(
            "qc_tool.frontend.dashboard.services.submissions.artifacts.CONFIG",
            {"submission_dir": str(self.submission_root)},
        )
        self.storage.start()
        self.addCleanup(self.storage.stop)

    def published(self):
        result = self.submit(self.owner, self.delivery, self.job_root)
        return DeliverySubmission.objects.get(pk=result.submission_uuid)

    def review_url(self, submission):
        return reverse("submission_review", args=(submission.pk,))

    def decision(self, submission, decision, *, notes="", version=None):
        return self.client.post(self.review_url(submission), {
            "decision": decision,
            "expected_review_version": submission.review_version if version is None else version,
            "notes": notes,
        })


@override_settings(SUBMISSION_ENABLED=True)
class SubmissionWorkspaceTests(SubmissionWorkspaceFixtureMixin, TestCase):
    def test_owner_cannot_approve_and_unassigned_manager_cannot_read_receipt(self):
        submission = self.published()
        self.client.force_login(self.owner)
        self.assertEqual(self.decision(submission, "approved").status_code, 403)
        self.client.force_login(self.unassigned)
        self.assertEqual(self.client.get(self.review_url(submission)).status_code, 404)
        self.assertEqual(self.decision(submission, "approved").status_code, 404)
        self.assertNotContains(self.client.get(reverse("submission_queue")), self.delivery.filename)
        submission.refresh_from_db()
        self.assertEqual(submission.review_state, "pending")

    def test_decline_needs_feedback_and_preserves_downloads_after_scratch_cleanup(self):
        submission = self.published()
        self.client.force_login(self.manager)
        self.assertContains(self.decision(submission, "declined"), "Give a reason")
        submission.refresh_from_db()
        self.assertEqual(submission.review_state, "pending")
        response = self.decision(submission, "declined", notes="Please correct the boundary extent.")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(get_product_coverage(self.release).submitted, 0)
        shutil.rmtree(self.job_root)
        shutil.rmtree(self.media_root / self.owner.username)
        self.client.force_login(self.owner)
        response = self.client.get(self.review_url(submission))
        self.assertContains(response, "Please correct the boundary extent.")
        self.assertContains(response, "upload a new ZIP")
        response = self.client.get(reverse("submission_file", args=(submission.pk, "input.d/delivery.zip")))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"delivery for workspace-owner")

    def test_download_scope_and_integrity_are_enforced(self):
        submission = self.published()
        url = reverse("submission_file", args=(submission.pk, "output.d/report.txt"))
        self.client.force_login(self.unassigned)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.manager)
        response = self.client.get(url)
        self.assertEqual(b"".join(response.streaming_content), b"validated")
        artifact = Path(submission.artifact_path) / "output.d/report.txt"
        artifact.write_text("tampered", encoding="utf-8")
        self.assertEqual(self.client.get(url).status_code, 404)
        artifact.unlink()
        artifact.symlink_to(self.job_root / "result.json")
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(reverse("submission_file", args=(submission.pk, "../result.json"))).status_code, 404)

    def test_invalid_manifest_is_unavailable_and_does_not_break_review_page(self):
        submission = self.published()
        self.client.force_login(self.manager)
        manifest = Path(submission.artifact_path) / "submission-manifest.json"
        for payload in ("[]", "null", '{"artifact_sha256": "invalid"}'):
            with self.subTest(payload=payload):
                manifest.write_text(payload, encoding="utf-8")
                response = self.client.get(self.review_url(submission))
                self.assertContains(response, "retained files are currently unavailable")

    def test_admin_review_and_stale_form_do_not_duplicate_decisions(self):
        submission = self.published()
        self.client.force_login(self.admin)
        self.assertEqual(self.decision(submission, "approved").status_code, 302)
        self.assertEqual(self.decision(submission, "declined", notes="Stale decision").status_code, 200)
        submission.refresh_from_db()
        self.assertEqual(submission.review_state, "accepted")
        self.assertEqual(submission.review_events.count(), 1)

    def test_csrf_is_required_for_review(self):
        submission = self.published()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.manager)
        response = client.post(self.review_url(submission), {"decision": "approved", "expected_review_version": 0})
        self.assertEqual(response.status_code, 403)

    def test_managers_browse_assigned_products_and_users_track_only_their_submissions(self):
        submission = self.published()
        other, delivery, _job, job_root = self.create_candidate("different-owner")
        self.submit(other, delivery, job_root)
        self.client.force_login(self.unassigned)
        self.assertNotContains(self.client.get(reverse("products")), "Test product")
        self.assertEqual(self.client.get(reverse("product_detail", args=(self.product.ident,))).status_code, 403)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse("submission_queue")), "My submissions")
        own = self.client.get(reverse("submission_queue"), {"state": "all"})
        self.assertEqual(list(own.context["review_items"]), [submission])
        self.client.force_login(self.manager)
        page = self.client.get(reverse("submission_queue"), {"state": "all", "delivery": self.delivery.pk})
        self.assertEqual(list(page.context["review_items"]), [submission])


@override_settings(SUBMISSION_ENABLED=True)
class PlanActivationWorkspaceTests(SubmissionWorkspaceFixtureMixin, TestCase):
    initial_coverage_state = ProductRelease.CoverageState.DRAFT

    def test_plan_activation_enables_existing_qc_and_manager_approval(self):
        with self.assertRaises(SubmissionError):
            self.submit(self.owner, self.delivery, self.job_root)
        self.client.force_login(self.admin)
        plan_url = reverse("product_plan_edit", args=(self.product.ident, self.release.pk))
        plan_form = self.client.get(plan_url).context["form"]
        response = self.client.post(plan_url, {
            "expected_manager_digest": plan_form.initial["expected_manager_digest"],
            "expected_release_id": self.release.pk,
            "aoi_codes": "EE001L1",
            "product_managers": [self.manager.pk],
            "confirm_approval": "on",
        })
        self.assertRedirects(response, reverse("product_detail", args=(self.product.ident,)))
        active = ProductRelease.objects.get(product=self.product, is_current=True)
        self.assertEqual(active.coverage_state, "authoritative")
        submission = self.published()
        self.job.refresh_from_db()
        self.assertEqual(self.job.product_release_id, self.release.pk)
        self.assertEqual(submission.product_release_id, active.pk)
        self.assertEqual(get_product_coverage(active).submitted, 0)
        self.client.force_login(self.manager)
        self.assertContains(self.client.get(self.review_url(submission)), "Approve submission")
        response = self.decision(submission, "approved", notes="Verified retained ZIP and QC report.")
        self.assertRedirects(response, self.review_url(submission))
        self.assertEqual(get_product_coverage(active).submitted, 1)
        self.client.force_login(self.owner)
        response = self.client.get(self.review_url(submission))
        self.assertContains(response, "Verified retained ZIP and QC report.")
        self.assertNotContains(response, "Approve submission")
