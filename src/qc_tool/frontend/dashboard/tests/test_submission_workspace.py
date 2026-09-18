"""Exercise plan activation, owner tracking, review and retained downloads."""

from pathlib import Path
from dataclasses import replace
import re
import shutil
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from qc_tool.frontend.accounts.authorization import AccountAccess
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.dashboard.models import DeliverySubmission, ProductRelease
from qc_tool.frontend.dashboard.services.catalog import get_product_coverage
from qc_tool.frontend.dashboard.services.submissions import SubmissionError
from qc_tool.frontend.dashboard.services.submissions.access import can_view_submission, visible_submissions
from qc_tool.frontend.dashboard.services.submissions.presentation import correction_context, current_review_feedback
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

    def deliveries_url(self, workflow):
        return "{}?delivery_view={}".format(reverse("deliveries"), workflow)

    def assert_current_workspace_link(self, response, route_name):
        navigation = re.search(
            r'<nav\b[^>]*aria-label="QC Tool workspace"[^>]*>(.*?)</nav>',
            response.content.decode(response.charset), flags=re.DOTALL,
        )
        self.assertIsNotNone(navigation)
        current_links = re.findall(r'<a\b[^>]*aria-current="page"[^>]*>', navigation.group(1))
        self.assertEqual(len(current_links), 1)
        self.assertIn('href="{}"'.format(reverse(route_name)), current_links[0])

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
        self.assertEqual(get_product_coverage(self.release).accepted, 0)
        shutil.rmtree(self.job_root)
        shutil.rmtree(self.media_root / self.owner.username)
        self.client.force_login(self.owner)
        response = self.client.get(self.review_url(submission))
        self.assertContains(response, "Please correct the boundary extent.")
        self.assertContains(response, "Rejected · corrections requested")
        self.assertContains(response, "keep the exact filename")
        self.assertContains(response, "Upload correction")
        response = self.client.get(reverse("submission_file", args=(submission.pk, "input.d/delivery.zip")))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"delivery for workspace-owner")

    def test_rejection_feedback_is_prominent_escaped_and_linked_to_owner_correction(self):
        submission = self.published()
        notes = 'Correct the <script>alert("extent")</script> boundary.\nInclude all required tiles.'
        self.client.force_login(self.manager)
        self.assertContains(self.client.get(self.review_url(submission)), "Reject and request corrections")
        self.assertEqual(self.decision(submission, "declined", notes=notes).status_code, 302)
        submission.refresh_from_db()
        self.client.force_login(self.owner)
        response = self.client.get(self.review_url(submission))
        event = submission.review_events.get()
        self.assertEqual(response.context["review_feedback"], event)
        self.assertEqual(response.context["correction"]["feedback"], event)
        self.assertContains(response, "Feedback from <strong>assigned-manager</strong>")
        self.assertContains(response, "&lt;script&gt;alert(&quot;extent&quot;)&lt;/script&gt;")
        self.assertNotContains(response, '<script>alert("extent")</script>')
        self.assertContains(response, '?correction_for={}'.format(submission.pk))
        self.assertContains(response, 'datetime="{}"'.format(event.created_at.isoformat()))
        self.assertLess(response.content.index(b"correction-heading"), response.content.index(b"Submitted delivery and QC evidence"))
        self.assertNotContains(response, "Reject and request corrections")
        self.assertContains(response, 'href="{}"'.format(self.deliveries_url("action_required")))

    def test_correction_upload_keeps_feedback_and_limits_access_to_rejected_owner(self):
        submission = self.published()
        self.client.force_login(self.manager)
        self.decision(submission, "declined", notes="Fix the extent. <script>unsafe()</script>")
        url = "{}?correction_for={}".format(reverse("file_upload"), submission.pk)
        self.client.force_login(self.owner)
        response = self.client.get(url)
        self.assertContains(response, "Upload a correction")
        self.assertContains(response, "Fix the extent. &lt;script&gt;unsafe()&lt;/script&gt;")
        self.assertContains(response, "Uploading a correction does not submit it automatically.")
        self.assertContains(response, 'data-correction-submission="{}"'.format(submission.pk))
        self.assertContains(response, 'data-correction-filename="{}"'.format(submission.delivery.filename))
        self.assertContains(response, 'data-correction-delivery-id="{}"'.format(submission.delivery_id))
        self.assertNotContains(response, "Use a different filename")
        self.assertEqual(response.context["correction"]["submission"].pk, submission.pk)
        self.assertIsNone(self.client.get(reverse("file_upload")).context["correction"])
        for invalid in ("", "not-a-uuid", "00000000-0000-0000-0000-000000000000"):
            self.assertEqual(self.client.get(reverse("file_upload"), {"correction_for": invalid}).status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.unassigned)
        self.assertIn(self.client.get(url).status_code, (403, 404))
        DeliverySubmission.objects.filter(pk=submission.pk).update(review_state="accepted")
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_reviewers_read_feedback_but_only_uploader_can_start_a_correction(self):
        submission = self.published()
        self.client.force_login(self.manager)
        self.decision(submission, "declined", notes="Correct the coverage gaps.")
        submission.refresh_from_db()
        for reviewer in (self.manager, self.admin):
            with self.subTest(reviewer=reviewer.username):
                self.client.force_login(reviewer)
                response = self.client.get(self.review_url(submission))
                self.assertContains(response, "Correct the coverage gaps.")
                self.assertNotContains(response, "Upload correction")
                self.assertIsNone(response.context["correction"])
        other = get_user_model().objects.create_user("other-review-owner", password="password")
        UserProductGrant.objects.create(user=other, product_ident=self.product.ident)
        for outsider in (self.unassigned, other):
            self.client.force_login(outsider)
            self.assertEqual(self.client.get(self.review_url(submission)).status_code, 404)
            self.assertFalse(can_view_submission(
                AccountAccess.from_user(outsider), owner_id=self.owner.pk, product_ident=self.product.ident,
            ))
        owner_access = AccountAccess.from_user(self.owner)
        self.assertIsNotNone(correction_context(submission, owner_access))
        self.assertIsNone(correction_context(submission, replace(owner_access, permissions=frozenset())))
        self.assertIsNone(correction_context(submission, AccountAccess.anonymous()))

    def test_manager_cannot_track_own_submission_after_assignment_is_revoked(self):
        submission = self.published()
        self.owner.groups.add(Group.objects.get(name="product_manager"))
        self.owner.product_grants.all().delete()
        self.client.force_login(self.owner)
        response = self.client.get(self.review_url(submission))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.decision(submission, "approved").status_code, 404)
        queue = self.client.get(reverse("submission_queue"), {"state": "all"})
        self.assertEqual(list(queue.context["review_items"]), [])

    def test_owner_receipt_and_retained_files_require_recipe_or_recorded_parent_grant(self):
        self.product.ident = "catalog-parent"
        self.product.save(update_fields=("ident",))
        submission = self.published()
        download_url = reverse(
            "submission_file", args=(submission.pk, "output.d/report.txt"),
        )
        self.client.force_login(self.owner)
        for granted in (self.job.product_ident, self.product.ident):
            with self.subTest(granted=granted):
                self.owner.product_grants.update(product_ident=granted)
                access = AccountAccess.from_user(self.owner)
                self.assertTrue(can_view_submission(
                    access, owner_id=self.owner.pk,
                    product_ident=self.product.ident,
                    recipe_ident=self.job.product_ident,
                ))
                self.assertEqual(list(visible_submissions(access)), [submission])
                self.assertEqual(self.client.get(self.review_url(submission)).status_code, 200)
                response = self.client.get(download_url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(b"".join(response.streaming_content), b"validated")

        self.owner.product_grants.update(product_ident="unrelated-product")
        access = AccountAccess.from_user(self.owner)
        self.assertFalse(can_view_submission(
            access, owner_id=self.owner.pk,
            product_ident=self.product.ident, recipe_ident=self.job.product_ident,
        ))
        self.assertFalse(visible_submissions(access).exists())
        self.assertEqual(self.client.get(self.review_url(submission)).status_code, 404)
        self.assertEqual(self.client.get(download_url).status_code, 404)
        self.assertRedirects(
            self.client.get(reverse("submission_queue")),
            self.deliveries_url("in_review"),
            fetch_redirect_response=False,
        )

        for reviewer in (self.manager, self.admin):
            with self.subTest(reviewer=reviewer.username):
                self.client.force_login(reviewer)
                response = self.client.get(download_url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(b"".join(response.streaming_content), b"validated")

    def test_feedback_matches_current_decision_and_version(self):
        old_rejection = SimpleNamespace(version=1, decision="declined", notes="Old feedback")
        current_approval = SimpleNamespace(version=2, decision="approved", notes="Approved after review")
        receipt = SimpleNamespace(review_version=2, review_state="rejected")
        self.assertIsNone(current_review_feedback(receipt, events=[old_rejection, current_approval]))
        current_rejection = SimpleNamespace(version=2, decision="declined", notes="Current feedback")
        self.assertIs(current_review_feedback(receipt, events=[old_rejection, current_rejection]), current_rejection)

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
        self.assertRedirects(
            self.client.get(reverse("submission_queue")),
            self.deliveries_url("in_review"),
        )
        own = self.client.get(reverse("deliveries_json"), {"delivery_view": "in_review"})
        self.assertEqual(own.status_code, 200)
        self.assertEqual([row["id"] for row in own.json()["rows"]], [self.delivery.pk])
        self.assertEqual(own.json()["rows"][0]["submission_url"], self.review_url(submission))
        self.client.force_login(self.manager)
        page = self.client.get(reverse("submission_queue"), {"state": "all", "delivery": self.delivery.pk})
        self.assertEqual(list(page.context["review_items"]), [submission])

    def test_default_user_legacy_submission_queue_opens_deliveries_in_review(self):
        self.client.force_login(self.owner)
        for query in ({}, {"state": "all"}, {"product": self.product.ident, "delivery": self.delivery.pk}):
            with self.subTest(query=query):
                self.assertRedirects(
                    self.client.get(reverse("submission_queue"), query),
                    self.deliveries_url("in_review"),
                    fetch_redirect_response=False,
                )

    def test_owner_submission_receipt_returns_to_matching_delivery_workflow(self):
        submission = self.published()
        self.client.force_login(self.owner)
        for state, workflow in (
            ("pending", "in_review"), ("conflict", "in_review"),
            ("accepted", "completed"), ("rejected", "action_required"),
        ):
            with self.subTest(state=state):
                DeliverySubmission.objects.filter(pk=submission.pk).update(review_state=state)
                response = self.client.get(self.review_url(submission))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Back to deliveries")
                self.assertContains(response, 'href="{}"'.format(self.deliveries_url(workflow)), count=2)
                self.assertContains(response, '<span aria-current="page">Submission</span>', html=True)
                self.assertNotContains(response, 'href="{}"'.format(reverse("submission_queue")))
                self.assert_current_workspace_link(response, "deliveries")

    def test_reviewer_submission_receipt_keeps_review_queue_navigation(self):
        submission = self.published()
        for reviewer in (self.manager, self.admin):
            with self.subTest(reviewer=reviewer.username):
                self.client.force_login(reviewer)
                response = self.client.get(self.review_url(submission))
                self.assertContains(response, "Back to submissions")
                self.assertEqual(response.context["submission_workspace_url"], reverse("submission_queue"))
                self.assertContains(response, '<span aria-current="page">Review</span>', html=True)
                self.assert_current_workspace_link(response, "submission_queue")
                queue = self.client.get(reverse("submission_queue"))
                self.assertContains(queue, "Submission review")
                self.assertEqual(queue.context["selected_state"], "pending")


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
            "product_unit_codes": "ee001l",
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
        self.assertEqual(get_product_coverage(active).accepted, 0)
        self.client.force_login(self.manager)
        self.assertContains(self.client.get(self.review_url(submission)), "Approve submission")
        response = self.decision(submission, "approved", notes="Verified retained ZIP and QC report.")
        self.assertRedirects(response, self.review_url(submission))
        self.assertEqual(get_product_coverage(active).accepted, 1)
        self.client.force_login(self.owner)
        response = self.client.get(self.review_url(submission))
        self.assertContains(response, "Verified retained ZIP and QC report.")
        self.assertNotContains(response, "Approve submission")
