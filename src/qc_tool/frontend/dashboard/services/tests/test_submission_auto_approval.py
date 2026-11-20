"""Deployment policy that approves uncontested published submissions."""

from unittest.mock import patch

from django.test import TestCase
from django.test import override_settings

from qc_tool.frontend.dashboard.models import DeliverySubmission
from qc_tool.frontend.dashboard.models import Product
from qc_tool.frontend.dashboard.models import ProductRelease
from qc_tool.frontend.dashboard.models import SubmissionConflict
from qc_tool.frontend.dashboard.models import SubmissionReviewEvent
from qc_tool.frontend.dashboard.services.catalog import get_product_coverage
from qc_tool.frontend.dashboard.services.submissions.auto_approval import (
    AUTOMATIC_REVIEWER_USERNAME,
)
from qc_tool.frontend.dashboard.services.submissions.publication import (
    publish_reserved_submission,
)

from .test_submissions import SubmissionFixtureMixin


ACCEPTED = DeliverySubmission.ReviewState.ACCEPTED
CONFLICT = DeliverySubmission.ReviewState.CONFLICT
PENDING = DeliverySubmission.ReviewState.PENDING


class SubmissionAutoApprovalTests(SubmissionFixtureMixin, TestCase):
    def submit_candidate(self, username):
        user, delivery, _job, job_root = self.create_candidate(username)
        result = self.submit(user, delivery, job_root)
        return user, delivery, job_root, result

    def submission_for(self, delivery):
        return DeliverySubmission.objects.get(delivery=delivery)

    @override_settings(QC_TOOL_AUTO_APPROVE_SUBMISSIONS=False)
    def test_disabled_policy_leaves_submission_awaiting_review(self):
        _user, delivery, _root, result = self.submit_candidate("manual-owner")

        self.assertEqual(result.review_state, PENDING)
        submission = self.submission_for(delivery)
        self.assertEqual((submission.review_state, submission.review_version), (PENDING, 0))
        self.assertFalse(SubmissionReviewEvent.objects.exists())

    @override_settings(QC_TOOL_AUTO_APPROVE_SUBMISSIONS=True)
    def test_uncontested_submission_is_approved_by_the_system_actor(self):
        _user, delivery, _root, result = self.submit_candidate("auto-owner")

        self.assertEqual(result.review_state, ACCEPTED)
        self.assertIsNone(result.conflict_id)
        submission = self.submission_for(delivery)
        self.assertEqual(submission.publication_state, DeliverySubmission.PublicationState.PUBLISHED)
        self.assertEqual((submission.review_state, submission.review_version), (ACCEPTED, 1))
        event = submission.review_events.get()
        self.assertEqual(event.decision, SubmissionReviewEvent.Decision.APPROVED)
        self.assertEqual(event.version, 1)
        self.assertIsNone(event.actor_id)
        self.assertEqual(event.actor_username, AUTOMATIC_REVIEWER_USERNAME)
        self.assertIn("QC_TOOL_AUTO_APPROVE_SUBMISSIONS", event.notes)
        self.assertEqual(get_product_coverage(self.release).accepted, 1)
        self.assertFalse(SubmissionConflict.objects.exists())

    @override_settings(QC_TOOL_AUTO_APPROVE_SUBMISSIONS=True)
    def test_idempotent_retry_does_not_record_a_second_approval(self):
        user, delivery, job_root, _result = self.submit_candidate("auto-retry-owner")

        retry = self.submit(user, delivery, job_root)

        self.assertTrue(retry.idempotent)
        self.assertEqual(retry.review_state, ACCEPTED)
        self.assertEqual(SubmissionReviewEvent.objects.count(), 1)
        self.assertEqual(self.submission_for(delivery).review_version, 1)

    @override_settings(QC_TOOL_AUTO_APPROVE_SUBMISSIONS=True)
    def test_submission_competing_with_an_approval_opens_a_conflict(self):
        _first_user, first_delivery, _root, _first = self.submit_candidate("auto-first")
        _second_user, second_delivery, _root, second = self.submit_candidate("auto-second")

        self.assertEqual(second.review_state, CONFLICT)
        self.assertIsNotNone(second.conflict_id)
        self.assertEqual(self.submission_for(first_delivery).review_state, ACCEPTED)
        second_submission = self.submission_for(second_delivery)
        self.assertEqual(second_submission.review_state, CONFLICT)
        self.assertFalse(second_submission.review_events.exists())
        self.assertEqual(SubmissionConflict.objects.get().state, SubmissionConflict.State.OPEN)
        self.assertEqual(get_product_coverage(self.release).accepted, 1)

    def test_submission_competing_with_a_pending_candidate_is_not_approved(self):
        with override_settings(QC_TOOL_AUTO_APPROVE_SUBMISSIONS=False):
            _user, first_delivery, _root, _first = self.submit_candidate("pending-first")
        with override_settings(QC_TOOL_AUTO_APPROVE_SUBMISSIONS=True):
            _user, second_delivery, _root, second = self.submit_candidate("pending-second")

        self.assertEqual(second.review_state, CONFLICT)
        self.assertEqual(self.submission_for(first_delivery).review_state, CONFLICT)
        self.assertEqual(self.submission_for(second_delivery).review_state, CONFLICT)
        self.assertFalse(SubmissionReviewEvent.objects.exists())

    def test_previously_declined_submission_does_not_block_approval(self):
        with override_settings(QC_TOOL_AUTO_APPROVE_SUBMISSIONS=False):
            reviewer, first_delivery, _root, _first = self.submit_candidate("declined-first")
            self.review(
                self.submission_for(first_delivery), reviewer,
                decision="declined", notes="Corrections are required.",
            )
        with override_settings(QC_TOOL_AUTO_APPROVE_SUBMISSIONS=True):
            _user, second_delivery, _root, second = self.submit_candidate("declined-second")

        self.assertEqual(second.review_state, ACCEPTED)
        self.assertIsNone(second.conflict_id)
        self.assertEqual(
            self.submission_for(first_delivery).review_state,
            DeliverySubmission.ReviewState.REJECTED,
        )
        self.assertEqual(
            self.submission_for(second_delivery).review_events.get().actor_username,
            AUTOMATIC_REVIEWER_USERNAME,
        )

    def submit_with_change_during_publication(self, username, change):
        """Reservation validates the product; it may change while files are copied."""

        user, delivery, _job, job_root = self.create_candidate(username)

        def publish_after_change(*args, **kwargs):
            change()
            return publish_reserved_submission(*args, **kwargs)

        with patch(
            "qc_tool.frontend.dashboard.services.submissions.lifecycle.publish_reserved_submission",
            side_effect=publish_after_change,
        ):
            return delivery, self.submit(user, delivery, job_root)

    @override_settings(QC_TOOL_AUTO_APPROVE_SUBMISSIONS=True)
    def test_inactive_delivery_plan_leaves_submission_awaiting_review(self):
        delivery, result = self.submit_with_change_during_publication(
            "draft-plan-owner",
            lambda: ProductRelease.objects.filter(pk=self.release.pk).update(
                coverage_state=ProductRelease.CoverageState.DRAFT,
            ),
        )

        self.assertEqual(result.review_state, PENDING)
        submission = self.submission_for(delivery)
        self.assertEqual(submission.publication_state, DeliverySubmission.PublicationState.PUBLISHED)
        self.assertEqual(submission.review_state, PENDING)
        self.assertFalse(SubmissionReviewEvent.objects.exists())

    @override_settings(QC_TOOL_AUTO_APPROVE_SUBMISSIONS=True)
    def test_archived_product_leaves_submission_awaiting_review(self):
        delivery, result = self.submit_with_change_during_publication(
            "archived-product-owner",
            lambda: Product.objects.filter(pk=self.product.pk).update(is_active=False),
        )

        self.assertEqual(result.review_state, PENDING)
        self.assertEqual(
            self.submission_for(delivery).publication_state,
            DeliverySubmission.PublicationState.PUBLISHED,
        )
        self.assertFalse(SubmissionReviewEvent.objects.exists())
