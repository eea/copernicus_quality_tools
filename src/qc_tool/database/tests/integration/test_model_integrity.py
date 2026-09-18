"""Fresh-schema integrity and index coverage on SQLite and PostgreSQL."""

from uuid import UUID

from django.contrib.auth import get_user_model
from django.db import connection, IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from qc_tool.database.checks.schema import verify_declared_constraints_and_indexes
from qc_tool.frontend.accounts.models import (
    PersonalAccessToken, UserProductGrant, UserRegionGrant,
)
from qc_tool.frontend.dashboard.models import (
    Delivery, DeliverySubmission, Job, Product, ProductRelease,
    ProductReleaseDefinition, ProductUnit, SubmissionConflict,
    SubmissionConflictEvent, SubmissionReviewEvent,
)
from qc_tool.frontend.dashboard.services.submissions.conflicts.resolution import _select_candidate


class DatabaseModelIntegrityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="schema-unit-owner")
        cls.product = Product.objects.create(ident="schema-product", name="Schema product")
        cls.release = ProductRelease.objects.create(
            product=cls.product, release_key="schema-stream", revision=1,
            description="Schema fixture", catalog_digest="a" * 64,
            coverage_state="authoritative", approved_at=timezone.now(), is_current=True,
        )
        cls.unit = ProductUnit.objects.create(
            product_release=cls.release, product_unit_code="unit-01", provenance="test",
        )

    def receipt(self, *, ident, review_state="pending", publication_state="published", unit=None):
        unit = unit or self.unit
        delivery = Delivery.objects.create(user=self.user, filename=f"{ident}.zip", size_bytes=1)
        job = Job.objects.create(
            delivery=delivery, product_release=unit.product_release,
            product_ident=self.product.ident,
        )
        return DeliverySubmission.objects.create(
            submission_uuid=UUID(int=ident), delivery=delivery, job=job,
            product_release=unit.product_release, product_unit=unit,
            product_unit_code=unit.product_unit_code,
            submitted_product_unit_code=unit.product_unit_code,
            submitted_by=self.user, submitted_by_username=self.user.username,
            request_channel="browser", publication_state=publication_state,
            review_state=review_state, published_at=timezone.now(),
            artifact_path=f"/published/{ident}", artifact_digest="b" * 64,
            input_digest="c" * 64,
        )

    def test_only_one_published_accepted_receipt_per_unit(self):
        accepted = self.receipt(ident=1, review_state="accepted")
        candidate = self.receipt(ident=2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            DeliverySubmission.objects.filter(pk=candidate.pk).update(review_state="accepted")
        other_unit = ProductUnit.objects.create(
            product_release=self.release, product_unit_code="unit-02", provenance="test",
        )
        self.receipt(ident=3, review_state="accepted", unit=other_unit)
        self.receipt(ident=4, review_state="accepted", publication_state="pending")
        self.assertEqual(
            list(DeliverySubmission.objects.filter(
                product_unit=self.unit, publication_state="published", review_state="accepted",
            ).values_list("pk", flat=True)), [accepted.pk],
        )

    def test_replacement_releases_previous_acceptance_before_accepting_lower_uuid(self):
        previous = self.receipt(ident=2, review_state="accepted")
        replacement = self.receipt(ident=1)
        with transaction.atomic():
            _select_candidate(self.unit, replacement, actor=self.user, notes="Reviewed replacement.")
        previous.refresh_from_db()
        replacement.refresh_from_db()
        self.assertEqual((previous.review_state, replacement.review_state), ("rejected", "accepted"))
        self.assertEqual(previous.review_events.get().decision, "declined")
        self.assertEqual(replacement.review_events.get().decision, "approved")

    def test_delivery_size_cannot_be_negative_even_in_bulk_writes(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Delivery.objects.bulk_create([
                Delivery(user=self.user, filename="invalid.zip", size_bytes=-1),
            ])
        Delivery.objects.create(user=self.user, filename="empty.zip", size_bytes=0)

    def test_release_states_and_authoritative_approval_are_database_invariants(self):
        for update in (
            {"coverage_state": "invalid"},
            {"source_kind": "invalid"},
            {"approved_at": None},
        ):
            with self.subTest(update=update), self.assertRaises(IntegrityError), transaction.atomic():
                ProductRelease.objects.filter(pk=self.release.pk).update(**update)

    def test_invalid_submission_states_are_rejected_at_insert(self):
        for fields in (
            {"publication_state": "invalid"},
            {"review_state": "invalid"},
        ):
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), transaction.atomic():
                self.receipt(ident=1, **fields)
        with self.assertRaises(IntegrityError), transaction.atomic():
            receipt = self.receipt(ident=2)
            # Bulk inserts deliberately bypass the model's retained-history guard.
            receipt.pk = UUID(int=3)
            receipt.request_channel = "other"
            receipt.delivery = Delivery.objects.create(user=self.user, filename="other.zip", size_bytes=1)
            receipt.job = Job.objects.create(delivery=receipt.delivery, product_ident=self.product.ident)
            DeliverySubmission.objects.bulk_create([receipt])

    def test_review_events_require_a_supported_decision_and_decline_reason(self):
        receipt = self.receipt(ident=1)
        for decision, notes in (("invalid", "Reason"), ("declined", "")):
            with self.subTest(decision=decision), self.assertRaises(IntegrityError), transaction.atomic():
                SubmissionReviewEvent.objects.bulk_create([
                    SubmissionReviewEvent(
                        submission=receipt, version=1, decision=decision,
                        actor_username=self.user.username, notes=notes,
                    ),
                ])

    def test_conflict_events_require_supported_type_and_positive_version(self):
        conflict = SubmissionConflict.objects.create(product_unit=self.unit, opened_at=timezone.now())
        for event_type, version in (("invalid", 1), ("opened", 0)):
            with self.subTest(event_type=event_type, version=version), self.assertRaises(IntegrityError), transaction.atomic():
                SubmissionConflictEvent.objects.bulk_create([
                    SubmissionConflictEvent(conflict=conflict, event_type=event_type, version=version),
                ])

    def test_all_named_integrity_rules_exist_in_fresh_schema(self):
        verify_declared_constraints_and_indexes()

    def test_foreign_keys_reuse_existing_composite_indexes_without_single_column_duplicates(self):
        covered_foreign_keys = (
            (PersonalAccessToken, "user"), (UserProductGrant, "user"), (UserRegionGrant, "user"),
            (ProductRelease, "product"), (ProductUnit, "product_release"),
            (ProductReleaseDefinition, "product_release"), (Job, "delivery"),
            (DeliverySubmission, "product_release"), (DeliverySubmission, "product_unit"),
            (SubmissionReviewEvent, "submission"), (SubmissionConflictEvent, "conflict"),
        )
        with connection.cursor() as cursor:
            for model, field_name in covered_foreign_keys:
                column = model._meta.get_field(field_name).column
                with self.subTest(model=model.__name__, field=field_name):
                    constraints = connection.introspection.get_constraints(cursor, model._meta.db_table)
                    indexes = [entry for entry in constraints.values() if entry["index"] or entry["unique"]]
                    self.assertTrue(any(entry["columns"][0] == column for entry in indexes if entry["columns"]))
                    self.assertFalse(any(
                        entry["columns"] == [column] and not entry["unique"] for entry in indexes
                    ))
