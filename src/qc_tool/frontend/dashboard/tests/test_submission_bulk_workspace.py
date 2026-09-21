"""Browser bulk approvals preserve scope, versions and explicit confirmation."""

from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from qc_tool.frontend.dashboard.forms.submission_bulk_review import submission_selection_token
from qc_tool.frontend.dashboard.models import DeliverySubmission, ProductUnit
from qc_tool.frontend.dashboard.tests.test_submission_workspace import SubmissionWorkspaceFixtureMixin


@override_settings(SUBMISSION_ENABLED=True)
class SubmissionBulkWorkspaceTests(SubmissionWorkspaceFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.first = self.published()
        ProductUnit.objects.create(
            product_release=self.release, product_unit_code="ee002l",
            source_value="EE002L1", provenance="manifest",
        )
        owner, delivery, _job, root = self.create_candidate("second-owner", aoi="ee002l")
        self.second = DeliverySubmission.objects.get(pk=self.submit(owner, delivery, root).submission_uuid)
        self.client.force_login(self.manager)
        self.queue_url = reverse("submission_queue") + "?product=test-definition&state=pending&page=1"
        self.approve_url = reverse("submission_bulk_approve") + "?product=test-definition&state=pending&page=1"

    def selection(self):
        response = self.client.get(self.queue_url)
        return [item.bulk_selection for item in response.context["review_items"] if item.bulk_selection]

    def post(self, tokens, intent="preview", **extra):
        return self.client.post(self.approve_url, {"selection": tokens, "intent": intent, **extra})

    def assert_pending(self):
        self.assertEqual(DeliverySubmission.objects.filter(review_state="pending").count(), 2)
        self.assertFalse(self.first.review_events.exists())
        self.assertFalse(self.second.review_events.exists())

    def test_preview_changes_nothing_and_confirmation_approves_selected_with_feedback(self):
        response = self.client.get(self.queue_url)
        self.assertContains(response, "Test product")
        self.assertEqual(response.context["bulk_eligible_count"], 2)
        tokens = self.selection()
        self.assertEqual(len(tokens), 2)
        preview = self.post(tokens)
        self.assertContains(preview, "Approve 2 deliveries")
        self.assert_current_workspace_link(preview, "products")
        self.assert_pending()
        response = self.post(tokens, "approve", notes="Checked the retained reports.")
        self.assertRedirects(response, self.queue_url, fetch_redirect_response=False)
        for submission in (self.first, self.second):
            submission.refresh_from_db()
            self.assertEqual(submission.review_state, "accepted")
            event = submission.review_events.get()
            self.assertEqual(event.actor, self.manager)
            self.assertEqual(event.notes, "Checked the retained reports.")
        self.assertEqual(self.client.get(self.queue_url).context["bulk_eligible_count"], 0)
        self.assertEqual(self.post(tokens, "approve").status_code, 409)
        self.assertEqual(self.first.review_events.count(), 1)

    def test_selecting_one_submission_does_not_approve_unselected_deliveries(self):
        self.assertEqual(self.post(self.selection()[:1], "approve").status_code, 302)
        self.assertEqual(DeliverySubmission.objects.filter(review_state="accepted").count(), 1)
        self.assertEqual(DeliverySubmission.objects.filter(review_state="pending").count(), 1)

    def test_changed_review_blocks_whole_batch(self):
        tokens = self.selection()
        DeliverySubmission.objects.filter(pk=self.second.pk).update(review_version=1)
        response = self.post(tokens, "approve")
        self.assertContains(response, "No deliveries were approved", status_code=409)
        self.assertNotContains(response, "Confirm approval", status_code=409)
        self.assert_pending()

    def test_conflicts_are_excluded_from_selection_and_rechecked_after_preview(self):
        tokens = self.selection()
        owner, delivery, _job, root = self.create_candidate("new-competitor")
        self.submit(owner, delivery, root)
        response = self.client.get(self.queue_url)
        self.assertEqual(response.context["bulk_eligible_count"], 1)
        self.assertContains(response, "Review competing submissions individually.")
        self.assertEqual(self.post(tokens, "approve").status_code, 409)
        self.assertFalse(DeliverySubmission.objects.filter(review_state="accepted").exists())

    def test_stopped_product_and_published_state_control_queue_selection(self):
        self.product.is_active = False
        self.product.save(update_fields=("is_active",))
        response = self.client.get(self.queue_url)
        self.assertEqual(response.context["bulk_eligible_count"], 0)
        self.assertNotContains(response, 'data-submission-select aria-label=')
        self.assertContains(response, "No deliveries on this page are eligible")

    def test_permission_revocation_is_rechecked_and_does_not_disclose_rows(self):
        tokens = self.selection()
        self.manager.product_grants.all().delete()
        response = self.post(tokens, "approve")
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, self.delivery.filename, status_code=403)
        self.assert_pending()

    def test_owner_and_foreign_reviewer_cannot_use_manager_selection(self):
        tokens = self.selection()
        self.client.force_login(self.owner)
        self.assertEqual(self.post(tokens, "approve").status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.post(tokens, "approve").status_code, 400)
        self.assert_pending()

    def test_invalid_or_expired_tokens_and_empty_or_oversized_selection_fail_closed(self):
        tokens = self.selection()
        for selected in ([], ["invalid"], tokens + tokens, tokens * 16):
            with self.subTest(selected_count=len(selected)):
                self.assertEqual(self.post(selected, "approve").status_code, 400)
                self.assert_pending()
        with patch("django.core.signing.time.time", return_value=1):
            expired = submission_selection_token(self.first, self.manager.pk)
        self.assertEqual(self.post([expired], "approve").status_code, 400)
        self.assert_pending()

    def test_invalid_notes_keep_selection_for_correction_without_approving(self):
        response = self.post(self.selection(), "approve", notes="x" * 5001)
        self.assertContains(response, "at most 5000 characters", status_code=400)
        self.assertContains(response, "Approve 2 deliveries", status_code=400)
        self.assertEqual(len(response.context["selected_items"]), 2)
        self.assert_pending()

    def test_bulk_endpoint_requires_post_and_csrf(self):
        self.assertEqual(self.client.get(self.approve_url).status_code, 405)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.manager)
        self.assertEqual(client.post(self.approve_url, {"selection": self.selection(), "intent": "approve"}).status_code, 403)
        self.assert_pending()
