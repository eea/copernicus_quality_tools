"""Bulk reviews preserve scope, competing receipts, and atomic decision history."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from qc_tool.frontend.accounts.authorization import AccountAccess, access_for
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.dashboard.models import (
    DeliverySubmission, ProductRelease, ProductUnit, SubmissionConflict,
    SubmissionConflictEvent, SubmissionReviewEvent,
)
from qc_tool.frontend.dashboard.services.submissions import SubmissionError
from qc_tool.frontend.dashboard.services.submissions.bulk_review import (
    MAX_BULK_APPROVALS, annotate_bulk_approval_eligibility,
    bulk_approval_block_reason, bulk_approve_submissions,
)
from qc_tool.frontend.dashboard.services.submissions.review_history import record_review_decision
from qc_tool.frontend.dashboard.services.tests.test_submissions import SubmissionFixtureMixin


class BulkReviewFixtureMixin(SubmissionFixtureMixin):
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_superuser("bulk-admin", password="test")
        self.manager = get_user_model().objects.create_user("bulk-manager", password="test")
        self.manager.groups.add(Group.objects.get(name="product_manager"))
        UserProductGrant.objects.create(user=self.manager, product_ident=self.product.ident)

    def receipt(self, username, *, unit_code="ee001l", publication_state="published"):
        unit, _ = ProductUnit.objects.get_or_create(
            product_release=self.release, product_unit_code=unit_code,
            defaults={"provenance": "manifest"},
        )
        owner, delivery, job, job_root = self.create_candidate(username, aoi=unit_code)
        if publication_state == DeliverySubmission.PublicationState.PUBLISHED:
            result = self.submit(owner, delivery, job_root)
            return DeliverySubmission.objects.get(pk=result.submission_uuid)
        return DeliverySubmission.objects.create(
            delivery=delivery, job=job, product_release=self.release,
            product_unit=unit, product_unit_code=unit_code,
            submitted_product_unit_code=unit_code, submitted_by=owner,
            submitted_by_username=username, request_channel="browser",
            publication_state=publication_state,
        )

    def approve(self, *submissions, actor=None, notes=""):
        actor = actor or self.admin
        return bulk_approve_submissions(
            selections=[(item.pk, item.review_version) for item in submissions],
            actor=actor, account_access=access_for(actor), notes=notes,
        )

    def reason(self, submission):
        return bulk_approval_block_reason(
            annotate_bulk_approval_eligibility(DeliverySubmission.objects.all()).get(pk=submission.pk),
        )


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class BulkSubmissionReviewTests(BulkReviewFixtureMixin, TestCase):
    def test_approves_distinct_units_with_actor_notes_and_readiness_history(self):
        first = self.receipt("owner-one")
        second = self.receipt("owner-two", unit_code="ee002l")
        self.assertEqual(self.approve(first, second, actor=self.manager, notes="  Evidence checked.  "), 2)
        for submission in (first, second):
            submission.refresh_from_db()
            self.assertEqual(submission.review_state, DeliverySubmission.ReviewState.ACCEPTED)
            self.assertEqual(submission.review_version, 1)
            event = SubmissionReviewEvent.objects.get(submission=submission)
            self.assertEqual(event.actor, self.manager)
            self.assertEqual(event.actor_username, self.manager.username)
            self.assertEqual(event.notes, "Evidence checked.")
            self.assertEqual(event.decision, SubmissionReviewEvent.Decision.APPROVED)
        self.product.refresh_from_db()
        self.assertEqual(self.product.readiness_revision, 2)
        self.assertIsNone(self.product.ready_at)

    def test_default_user_anonymous_and_unassigned_manager_cannot_approve(self):
        submission = self.receipt("owner")
        self.manager.product_grants.all().delete()
        for access in (access_for(submission.submitted_by), access_for(self.manager), AccountAccess.anonymous()):
            with self.subTest(access=access), self.assertRaises(SubmissionError) as raised:
                bulk_approve_submissions(
                    selections=[(submission.pk, submission.review_version)],
                    actor=self.manager, account_access=access,
                )
            self.assertEqual(raised.exception.status_code, 403)
            self.assertNotIn(submission.delivery.filename, raised.exception.message)
        self.assertFalse(SubmissionReviewEvent.objects.exists())

    def test_missing_selection_does_not_approve_the_visible_part(self):
        submission = self.receipt("owner")
        with self.assertRaises(SubmissionError) as raised:
            bulk_approve_submissions(
                selections=[(submission.pk, 0), (uuid4(), 0)],
                actor=self.admin, account_access=access_for(self.admin),
            )
        self.assertEqual(raised.exception.status_code, 403)
        submission.refresh_from_db()
        self.assertEqual(submission.review_state, DeliverySubmission.ReviewState.PENDING)
        self.assertFalse(SubmissionReviewEvent.objects.exists())

    def test_invalid_selection_inputs_fail_before_database_writes(self):
        ident = uuid4()
        invalid = (
            None, [], "not-a-selection", [(ident, 0, "extra")], [None],
            [("bad-uuid", 0)], [(3, 0)], [(ident, True)], [(ident, "0")],
            [(ident, -1)], [(ident, 0), (str(ident), 0)],
            [(uuid4(), 0) for _ in range(MAX_BULK_APPROVALS + 1)],
        )
        for selections in invalid:
            with self.subTest(selections=selections), self.assertRaises(SubmissionError) as raised:
                bulk_approve_submissions(
                    selections=selections, actor=self.admin, account_access=access_for(self.admin),
                )
            self.assertEqual(raised.exception.status_code, 400)
        self.assertFalse(SubmissionReviewEvent.objects.exists())

    def test_notes_limit_rejects_whole_selection(self):
        submission = self.receipt("owner")
        with self.assertRaises(SubmissionError) as raised:
            self.approve(submission, notes="x" * 5_001)
        self.assertEqual(raised.exception.code, "review_notes_too_long")
        self.assertFalse(SubmissionReviewEvent.objects.exists())

    def test_stale_version_leaves_every_selected_receipt_unchanged(self):
        first = self.receipt("owner-one")
        second = self.receipt("owner-two", unit_code="ee002l")
        DeliverySubmission.objects.filter(pk=second.pk).update(review_version=1)
        with self.assertRaises(SubmissionError) as raised:
            self.approve(first, second)
        self.assertEqual(raised.exception.code, "submission_review_changed")
        self.assertFalse(DeliverySubmission.objects.filter(review_state="accepted").exists())
        self.assertFalse(SubmissionReviewEvent.objects.exists())
        self.product.refresh_from_db()
        self.assertEqual(self.product.readiness_revision, 0)

    def test_failure_while_recording_rolls_back_decisions_events_and_readiness(self):
        first = self.receipt("owner-one")
        second = self.receipt("owner-two", unit_code="ee002l")
        writes = 0

        def write_then_fail(*args, **kwargs):
            nonlocal writes
            writes += 1
            record_review_decision(*args, **kwargs)
            if writes == 2:
                raise RuntimeError("Simulated second-write failure")

        with patch(
            "qc_tool.frontend.dashboard.services.submissions.bulk_review.record_review_decision",
            side_effect=write_then_fail,
        ), self.assertRaises(RuntimeError):
            self.approve(first, second)
        self.assertFalse(DeliverySubmission.objects.filter(review_state="accepted").exists())
        self.assertFalse(SubmissionReviewEvent.objects.exists())
        self.product.refresh_from_db()
        self.assertEqual(self.product.readiness_revision, 0)

    def test_unfinished_publications_are_not_eligible(self):
        for index, state in enumerate(("pending", "publishing", "failed")):
            submission = self.receipt(f"owner-{state}", unit_code=f"ee00{index + 1}l", publication_state=state)
            with self.subTest(state=state), self.assertRaises(SubmissionError) as raised:
                self.approve(submission)
            self.assertEqual(raised.exception.code, "submission_not_published")
            self.assertTrue(self.reason(submission))
        self.assertFalse(SubmissionReviewEvent.objects.exists())

    def test_previously_reviewed_receipts_are_not_reapproved(self):
        for index, state in enumerate(("accepted", "rejected")):
            submission = self.receipt(f"owner-{state}", unit_code=f"ee00{index + 1}l")
            DeliverySubmission.objects.filter(pk=submission.pk).update(review_state=state)
            with self.subTest(state=state), self.assertRaises(SubmissionError) as raised:
                self.approve(submission)
            self.assertEqual(raised.exception.code, "submission_already_reviewed")
            self.assertTrue(self.reason(submission))
        self.assertFalse(SubmissionReviewEvent.objects.exists())

    def test_stopped_product_and_non_authoritative_plan_block_approval(self):
        submission = self.receipt("owner")
        self.product.is_active = False
        self.product.save(update_fields=("is_active",))
        with self.assertRaises(SubmissionError) as raised:
            self.approve(submission)
        self.assertEqual(raised.exception.code, "product_archived")
        self.assertTrue(self.reason(submission))
        self.product.is_active = True
        self.product.save(update_fields=("is_active",))
        for state in ("unknown", "draft", "retired"):
            ProductRelease.objects.filter(pk=self.release.pk).update(coverage_state=state)
            with self.subTest(state=state), self.assertRaises(SubmissionError) as raised:
                self.approve(submission)
            self.assertEqual(raised.exception.code, "delivery_plan_not_active")
            self.assertTrue(self.reason(submission))
        self.assertFalse(SubmissionReviewEvent.objects.exists())

    def test_same_unit_selection_and_open_conflict_need_individual_review(self):
        first = self.receipt("owner-one")
        second = self.receipt("owner-two")
        first.refresh_from_db()
        with self.assertRaises(SubmissionError) as raised:
            self.approve(first, second)
        self.assertEqual(raised.exception.code, "bulk_duplicate_product_unit")
        with self.assertRaises(SubmissionError) as raised:
            self.approve(first)
        self.assertEqual(raised.exception.code, "bulk_competing_submissions")
        self.assertTrue(self.reason(first))
        self.assertFalse(SubmissionReviewEvent.objects.exists())

    def test_open_conflict_blocks_even_a_lone_pending_candidate(self):
        submission = self.receipt("owner")
        SubmissionConflict.objects.create(product_unit=self.product_unit, opened_at=timezone.now())
        with self.assertRaises(SubmissionError) as raised:
            self.approve(submission)
        self.assertEqual(raised.exception.code, "bulk_competing_submissions")
        self.assertTrue(self.reason(submission))

    def test_competitors_block_even_without_an_open_conflict(self):
        first = self.receipt("owner-one")
        second = self.receipt("owner-two")
        SubmissionConflict.objects.filter(product_unit=self.product_unit).update(
            state="dismissed", resolved_at=timezone.now(),
        )
        DeliverySubmission.objects.filter(pk=first.pk).update(review_state="pending")
        first.refresh_from_db()
        for state in ("pending", "conflict", "accepted"):
            DeliverySubmission.objects.filter(pk=second.pk).update(review_state=state)
            with self.subTest(state=state), self.assertRaises(SubmissionError) as raised:
                self.approve(first)
            self.assertEqual(raised.exception.code, "bulk_competing_submissions")
            self.assertTrue(self.reason(first))
        self.assertFalse(SubmissionReviewEvent.objects.exists())

    def test_closed_conflict_and_rejected_peers_remain_unchanged(self):
        previous = self.receipt("previous-owner")
        self.review(previous, self.manager, decision="declined", notes="Correct the data.")
        conflict = SubmissionConflict.objects.create(
            product_unit=self.product_unit, state="dismissed", opened_at=timezone.now(),
            resolved_at=timezone.now(), resolution_notes="Historical decision.",
        )
        submission = self.receipt("corrected-owner")
        history = list(SubmissionReviewEvent.objects.values())
        conflict_history = list(SubmissionConflictEvent.objects.values())
        self.assertEqual(self.reason(submission), "")
        self.assertEqual(self.approve(submission), 1)
        previous.refresh_from_db()
        conflict.refresh_from_db()
        self.assertEqual(previous.review_state, "rejected")
        self.assertEqual(previous.review_version, 1)
        self.assertEqual(conflict.state, "dismissed")
        self.assertEqual(conflict.version, 1)
        self.assertEqual(conflict.resolution_notes, "Historical decision.")
        self.assertEqual(list(SubmissionReviewEvent.objects.filter(submission=previous).values()), history)
        self.assertEqual(list(SubmissionConflictEvent.objects.values()), conflict_history)

    def test_queue_eligibility_has_no_per_row_queries(self):
        self.receipt("owner-one")
        self.receipt("owner-two", unit_code="ee002l")
        with self.assertNumQueries(1):
            reasons = [bulk_approval_block_reason(item) for item in annotate_bulk_approval_eligibility(
                DeliverySubmission.objects.all(),
            )]
        self.assertEqual(reasons, ["", ""])


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ConcurrentBulkSubmissionReviewTests(BulkReviewFixtureMixin, TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("Bulk review concurrency requires PostgreSQL locks.")
        super().setUp()

    def test_overlapping_batches_record_each_decision_only_once(self):
        first = self.receipt("owner-one")
        second = self.receipt("owner-two", unit_code="ee002l")
        barrier = Barrier(2)

        def approve(reverse):
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.admin.pk)
                access = access_for(actor)
                selections = [(first.pk, 0), (second.pk, 0)]
                barrier.wait(timeout=10)
                try:
                    return bulk_approve_submissions(
                        selections=list(reversed(selections)) if reverse else selections,
                        actor=actor, account_access=access,
                    )
                except SubmissionError as error:
                    return error.code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(approve, (False, True)))
        self.assertCountEqual(results, [2, "submission_review_changed"])
        self.assertEqual(SubmissionReviewEvent.objects.count(), 2)
        self.assertEqual(DeliverySubmission.objects.filter(review_state="accepted").count(), 2)
        self.product.refresh_from_db()
        self.assertEqual(self.product.readiness_revision, 2)
