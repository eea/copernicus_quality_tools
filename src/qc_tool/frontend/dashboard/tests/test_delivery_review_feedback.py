"""Review decisions remain visible to uploaders without exposing correspondence."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from qc_tool.common import JOB_OK
from qc_tool.frontend.accounts.authorization import access_for
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import UserProductGrant, UserProfile, UserRegionGrant
from qc_tool.frontend.dashboard.models import (
    Delivery, DeliverySubmission, Job, Product, ProductAOI, ProductRelease,
    SubmissionReviewEvent,
)
from qc_tool.frontend.dashboard.services.deliveries.listing import (
    count_delivery_statuses, query_deliveries,
)


class DeliveryReviewFeedbackTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user(username="feedback-owner")
        cls.other = get_user_model().objects.create_user(username="feedback-other")
        cls.manager = get_user_model().objects.create_user(username="feedback-manager")
        cls.manager.groups.add(Group.objects.get(name=Role.PRODUCT_MANAGER.value))
        cls.admin = get_user_model().objects.create_superuser(
            username="feedback-admin", email="admin@example.test", password="test",
        )
        cls.product = Product.objects.create(ident="feedback-product", name="Feedback product")
        cls.release = ProductRelease.objects.create(
            product=cls.product, release_key="feedback-v1", revision=1,
            catalog_digest="a" * 64, is_current=True,
        )
        cls.aoi = ProductAOI.objects.create(
            product_release=cls.release, aoi_code="CZ", provenance="manifest",
        )
        UserProductGrant.objects.create(user=cls.manager, product_ident=cls.product.ident)

    def submission(self, name, *, owner=None, state="rejected", version=1, publication_state="published"):
        owner = owner or self.owner
        now = timezone.now()
        delivery = Delivery.objects.create(
            user=owner, filename=name + ".zip", size_bytes=1024,
            product_ident=self.product.ident, date_submitted=now,
        )
        job = Job.objects.create(
            delivery=delivery, product_ident=self.product.ident,
            product_release=self.release, job_status=JOB_OK,
        )
        submission = DeliverySubmission.objects.create(
            delivery=delivery, job=job, product_release=self.release,
            product_aoi=self.aoi, aoi_code=self.aoi.aoi_code,
            aoi_code_submitted=self.aoi.aoi_code, submitted_by=owner,
            submitted_by_username=owner.username, request_channel="browser",
            publication_state=publication_state, review_state=state, review_version=version,
            published_at=now, artifact_path="/published/" + name,
            artifact_digest="b" * 64, input_digest="c" * 64,
        )
        return submission

    def event(self, submission, *, version=1, decision="declined", notes="Correct the missing geometry."):
        return SubmissionReviewEvent.objects.create(
            submission=submission, version=version, decision=decision,
            actor=self.manager, actor_username=self.manager.username, notes=notes,
        )

    def rows(self, user, **kwargs):
        return query_deliveries(user, account_access=access_for(user), **kwargs)[1]

    def test_rejected_receipt_preserves_qc_and_exposes_current_feedback_and_correction(self):
        submission = self.submission("correction-needed", version=2)
        self.event(submission, notes="An older comment.")
        event = self.event(submission, version=2, notes="Correct the geometry and upload again.")

        access = access_for(self.owner)
        with self.assertNumQueries(2):
            total, rows = query_deliveries(self.owner, account_access=access)

        self.assertEqual(total, 1)
        row = rows[0]
        self.assertEqual(row["delivery_status"], "needs_correction")
        self.assertEqual(row["last_job_status"], JOB_OK)
        self.assertEqual(row["submission_review_state"], "rejected")
        self.assertEqual(row["review_notes"], event.notes)
        self.assertEqual(row["review_actor_username"], self.manager.username)
        self.assertIsNotNone(row["review_created_at"])
        self.assertEqual(row["submission_id"], str(submission.pk))
        self.assertEqual(row["submission_url"], reverse("submission_review", args=(submission.pk,)))
        self.assertTrue(row["can_upload_correction"])
        self.assertEqual(
            row["correction_upload_url"],
            "{}?correction_for={}".format(reverse("file_upload"), submission.pk),
        )

    def test_status_buckets_and_counts_are_exclusive_and_follow_owner_and_filters(self):
        rejected = self.submission("needs-correction")
        self.event(rejected)
        for state in ("pending", "accepted", "conflict"):
            self.submission("review-" + state, state=state, version=0)
        self.submission("hidden-correction", owner=self.other)

        access = access_for(self.owner)
        with self.assertNumQueries(1):
            counts = count_delivery_statuses(access).as_dict()
        self.assertEqual(counts["all"], 4)
        self.assertEqual(counts["submitted"], 2)
        self.assertEqual(counts["accepted"], 1)
        self.assertEqual(counts["needs_correction"], 1)
        self.assertEqual(sum(value for name, value in counts.items() if name not in {"all", "attention"}), 4)
        self.assertEqual(
            {row["id"] for row in self.rows(self.owner, delivery_status="needs_correction")},
            {rejected.delivery_id},
        )
        self.assertEqual(len(self.rows(self.owner, delivery_status="submitted")), 2)
        self.assertEqual(count_delivery_statuses(access, search="review-").needs_correction, 0)

    def test_manager_and_administrator_can_read_feedback_but_only_owner_can_correct(self):
        submission = self.submission("assigned-correction")
        self.event(submission)

        for viewer in (self.manager, self.admin):
            with self.subTest(viewer=viewer.username):
                row = self.rows(viewer)[0]
                self.assertEqual(row["submission_review_state"], "rejected")
                self.assertTrue(row["review_notes"])
                self.assertFalse(row["can_upload_correction"])
                self.assertEqual(row["correction_upload_url"], "")
        self.assertEqual(self.rows(self.other), [])

    def test_delivery_browsing_grants_do_not_expose_review_feedback_or_correction_counts(self):
        submission = self.submission("private-correspondence")
        self.event(submission, notes="Private manager correspondence.")
        UserProfile.objects.create(user=self.owner, country="CZ")
        UserRegionGrant.objects.create(user=self.other, aoi_code="CZ")
        self.other.user_permissions.add(Permission.objects.get(
            content_type__app_label="accounts", codename="view_region_deliveries",
        ))

        access = access_for(self.other)
        total, rows = query_deliveries(self.other, account_access=access)
        self.assertEqual(total, 1)
        row = rows[0]
        self.assertEqual(row["delivery_status"], "submitted")
        for field in ("submission_id", "submission_review_state", "review_notes", "review_actor_username", "review_created_at"):
            self.assertIsNone(row[field])
        self.assertEqual(row["submission_url"], "")
        self.assertFalse(row["can_upload_correction"])
        self.assertEqual(count_delivery_statuses(access).needs_correction, 0)
        self.assertEqual(self.rows(self.other, delivery_status="needs_correction"), [])

    def test_changed_decision_does_not_show_stale_decline_and_pagination_does_not_duplicate_rows(self):
        approved = self.submission("approved-after-review", state="accepted", version=2)
        self.event(approved, notes="Old decline.")
        self.event(approved, version=2, decision="approved", notes="Correction verified.")
        conflict = self.submission("competing-submission", state="conflict", version=1)
        self.event(conflict, decision="approved", notes="Old approval.")

        rows = {row["id"]: row for row in self.rows(self.owner)}
        self.assertEqual(rows[approved.delivery_id]["review_notes"], "Correction verified.")
        self.assertIsNone(rows[conflict.delivery_id]["review_notes"])
        self.assertEqual({row["delivery_status"] for row in rows.values()}, {"submitted", "accepted"})
        self.assertEqual(len(self.rows(self.owner, limit=1, offset=1)), 1)

    def test_owner_who_is_manager_can_see_their_own_unassigned_review(self):
        self.owner.groups.add(Group.objects.get(name=Role.PRODUCT_MANAGER.value))
        submission = self.submission("manager-own-submission")
        self.event(submission)

        self.assertEqual(self.rows(self.owner)[0]["review_notes"], "Correct the missing geometry.")

    def test_rejection_is_first_in_attention_without_accepted_history(self):
        rejected = self.submission("older-rejected")
        self.event(rejected)
        self.submission("approved", state="accepted")
        self.submission("awaiting-review", state="pending")
        Delivery.objects.create(user=self.owner, filename="new-unvalidated.zip", size_bytes=1024)
        self.client.force_login(self.owner)
        payload = self.client.get(reverse("deliveries_json")).json()
        self.assertEqual([row["delivery_status"] for row in payload["rows"]], ["needs_correction", "not_validated"])
        self.assertEqual(payload["rows"][0]["id"], rejected.delivery_id)
        self.assertEqual(payload["status_counts"]["attention"], 2)
        self.assertEqual(payload["status_counts"]["submitted"], 1)
        self.assertEqual(payload["status_counts"]["accepted"], 1)

    def test_review_decisions_move_between_workflows_without_changing_submission(self):
        submission = self.submission("review-lifecycle", state="pending", version=0)
        self.client.force_login(self.owner)
        for state, expected_view, expected_status in (
            ("pending", "in_review", "submitted"),
            ("rejected", "action_required", "needs_correction"),
            ("accepted", "completed", "accepted"),
            ("conflict", "in_review", "submitted"),
        ):
            with self.subTest(state=state):
                submission.review_state = state
                submission.save(update_fields=["review_state"])
                payload = self.client.get(reverse("deliveries_json"), {
                    "delivery_view": expected_view,
                }).json()
                self.assertEqual(payload["total"], 1)
                self.assertEqual(payload["rows"][0]["submission_id"], str(submission.pk))
                self.assertEqual(payload["rows"][0]["delivery_status"], expected_status)
                self.assertEqual(payload["rows"][0]["workflow_stage"], expected_view)
                self.assertEqual(payload["workflow_counts"][expected_view], 1)
                self.assertEqual(sum(payload["workflow_counts"].values()), 2)

    def test_completed_view_and_counts_preserve_review_visibility(self):
        accepted = self.submission("private-acceptance", state="accepted")
        self.event(accepted, decision="approved", notes="Review completed.")
        UserProfile.objects.create(user=self.owner, country="CZ")
        UserRegionGrant.objects.create(user=self.other, aoi_code="CZ")
        self.other.user_permissions.add(Permission.objects.get(
            content_type__app_label="accounts", codename="view_region_deliveries",
        ))
        for viewer, visible in ((self.owner, True), (self.manager, True), (self.admin, True), (self.other, False)):
            with self.subTest(viewer=viewer.username):
                self.client.force_login(viewer)
                payload = self.client.get(reverse("deliveries_json"), {
                    "delivery_view": "completed",
                }).json()
                self.assertEqual(payload["total"], int(visible))
                self.assertEqual(payload["workflow_counts"]["completed"], int(visible))
                self.assertEqual(payload["status_counts"]["accepted"], int(visible))
                self.assertEqual(payload["workflow_counts"]["in_review"], int(not visible))

    def test_completed_requires_published_acceptance_and_is_exclusive_without_submission_date(self):
        accepted = self.submission("accepted-without-date", state="accepted")
        Delivery.objects.filter(pk=accepted.delivery_id).update(date_submitted=None)
        self.submission("unpublished-acceptance", state="accepted", publication_state="pending")
        access = access_for(self.owner)
        self.assertEqual([row["id"] for row in self.rows(self.owner, delivery_view="completed")], [accepted.delivery_id])
        self.assertEqual(self.rows(self.owner, delivery_view="action_required"), [])
        counts = count_delivery_statuses(access).as_dict()
        self.assertEqual(counts["accepted"], 1)
        self.assertEqual(counts["submitted"], 1)
        self.assertEqual(counts["attention"], 0)
