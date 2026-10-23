"""Create-only transfer contracts on isolated, model-created databases."""

from copy import deepcopy
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection, transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from qc_tool.database.transfers.errors import TransferError
from qc_tool.database.transfers.records import (
    apply_records, export_record_counts, export_records, plan_records, snapshot_current_application,
    validate_records, verify_records,
)
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.dashboard.models import (
    Delivery, DeliverySubmission, Job, Product, ProductRelease,
    ProductReleaseDefinition, ProductUnit, QcDefinition, SubmissionConflict,
    SubmissionConflictEvent, SubmissionReviewEvent,
)


class TransferRecordTests(TestCase):
    def setUp(self):
        self.source = get_user_model().objects.create_superuser(
            username="source-admin", email="source@example.test", password="test-password",
        )
        self.other = get_user_model().objects.create_user(username="excluded-account")

    def test_selective_accounts_exclude_credentials_and_other_users(self):
        UserProductGrant.objects.create(user=self.source, product_ident="source-product")
        payload = export_records("accounts", [self.source.pk])
        self.assertEqual(len(payload["accounts"]), 1)
        row = payload["accounts"][0]
        self.assertEqual(row["grants"], ["source-product"])
        self.assertEqual(payload["records"], {})
        self.assertNotIn("password", row)
        self.assertNotIn("is_superuser", row)
        self.assertNotIn("excluded-account", str(payload))

    def test_standard_bootstrap_accounts_export_in_both_profiles(self):
        commands = (
            ("admin", ("--superuser",)),
            ("guest", ()),
            ("product_manager", ("--group", Role.PRODUCT_MANAGER.value)),
        )
        for username, options in commands:
            call_command("create_default_user", "--username", username, "--password", username,
                         *options, stdout=StringIO())
        accounts = get_user_model().objects.filter(username__in=[name for name, _options in commands])
        ids = list(accounts.order_by("pk").values_list("pk", flat=True))
        for profile in ("accounts", "application"):
            with self.subTest(profile=profile):
                payload = export_records(profile, ids if profile == "accounts" else None)
                exported = {row["username"]: row for row in payload["accounts"]}
                for username, _options in commands:
                    self.assertIn(username, exported)
                    self.assertEqual(exported[username]["email"], "")
                    self.assertNotIn("password", exported[username])
                if profile == "accounts":
                    self.assertEqual(set(exported), {name for name, _options in commands})

    def test_blank_email_round_trip_preserves_inactive_account_access_boundary(self):
        payload = export_records("accounts", [self.other.pk])
        self.assertEqual(payload["accounts"][0]["email"], "")
        payload["accounts"][0]["username"] = "imported-blank-email"
        result = apply_records(payload, plan_records(payload), actor=self.source)
        imported = get_user_model().objects.get(pk=result["user_mappings"][str(self.other.pk)])
        self.assertEqual(imported.email, "")
        self.assertFalse(imported.is_active)
        self.assertFalse(imported.is_staff)
        self.assertFalse(imported.is_superuser)
        self.assertFalse(imported.has_usable_password())
        self.assertEqual(result["created_counts"], {"accounts": 1})
        verify_records(payload, result)

    def test_malformed_nonblank_import_email_is_rejected_before_writes(self):
        payload = export_records("accounts", [self.source.pk])
        payload["accounts"][0]["username"] = "invalid-email-import"
        before = get_user_model().objects.count()
        for email in ("product_manager@product_manager.com", "not-an-email"):
            with self.subTest(email=email):
                invalid = deepcopy(payload)
                invalid["accounts"][0]["email"] = email
                with self.assertRaisesMessage(TransferError, "email violates its field contract"):
                    plan_records(invalid)
                self.assertEqual(get_user_model().objects.count(), before)
                self.assertFalse(get_user_model().objects.filter(username="invalid-email-import").exists())

    def test_new_account_is_inactive_without_credentials_authority_or_grants(self):
        payload = export_records("accounts", [self.source.pk])
        payload["accounts"][0]["username"] = "imported-admin"
        payload["accounts"][0]["grants"] = ["source-product"]
        plan = plan_records(payload)
        result = apply_records(payload, plan, actor=self.source)
        imported = get_user_model().objects.get(pk=result["user_mappings"][str(self.source.pk)])
        self.assertFalse(imported.is_active)
        self.assertFalse(imported.is_staff)
        self.assertFalse(imported.is_superuser)
        self.assertFalse(imported.has_usable_password())
        self.assertFalse(imported.product_grants.exists())
        self.assertEqual(list(imported.groups.values_list("name", flat=True)), [Role.DEFAULT.value])
        self.assertFalse(imported.user_permissions.exists())

    def test_username_collision_requires_explicit_identity_mapping(self):
        payload = export_records("accounts", [self.source.pk])
        self.assertTrue(plan_records(payload)["blockers"])
        before = get_user_model().objects.values().get(pk=self.other.pk)
        plan = plan_records(payload, {str(self.source.pk): self.other.pk})
        self.assertFalse(plan["blockers"])
        apply_records(payload, plan)
        self.assertEqual(get_user_model().objects.values().get(pk=self.other.pk), before)

    def test_plan_rejects_changed_package_or_target_without_writes(self):
        payload = export_records("accounts", [self.source.pk])
        payload["accounts"][0]["username"] = "new-account"
        plan = plan_records(payload)
        payload["accounts"][0]["email"] = "changed@example.test"
        with self.assertRaisesMessage(TransferError, "stale"):
            apply_records(payload, plan)
        self.assertFalse(get_user_model().objects.filter(username="new-account").exists())
        payload["accounts"][0]["email"] = self.source.email
        plan = plan_records(payload)
        get_user_model().objects.filter(pk=self.other.pk).update(first_name="Changed target")
        with self.assertRaisesMessage(TransferError, "stale"):
            apply_records(payload, plan)

    def test_review_is_bound_to_the_database_destination(self):
        payload = export_records("accounts", [self.source.pk])
        payload["accounts"][0]["username"] = "new-account"
        plan = plan_records(payload)
        for key, value in (("NAME", "another-database"), ("HOST", "another-host.invalid"), ("PORT", "15432")):
            with self.subTest(key=key), patch.dict(connection.settings_dict, {key: value}):
                # The open disposable connection/records are unchanged. A
                # different configured destination alone invalidates consent.
                with self.assertRaisesMessage(TransferError, "stale"):
                    apply_records(payload, plan)
        self.assertFalse(get_user_model().objects.filter(username="new-account").exists())

    def test_future_or_malformed_contract_fails_closed(self):
        payload = export_records("accounts", [self.source.pk])
        for mutate in (
            lambda data: data.update(contract="0" * 64),
            lambda data: data.update(format=2),
            lambda data: data["accounts"][0].update(is_superuser=True),
            lambda data: data["accounts"][0].update(grants=[{}]),
            lambda data: data["accounts"][0].update(date_joined="2026-01-01T00:00:00+00:00"),
            lambda data: data.update(records={"users": []}),
        ):
            changed = deepcopy(payload)
            mutate(changed)
            with self.assertRaises(TransferError):
                validate_records(changed)

    def fixture_graph(self):
        product = Product.objects.create(ident="transfer-product", name="Transfer product")
        definition = QcDefinition.objects.create(
            product_ident="transfer-product", digest="a" * 64,
            description="Fixture", document={"description": "Fixture"}, source_path="original.json",
        )
        release = ProductRelease.objects.create(
            product=product, release_key="transfer-stream", revision=1,
            description="Fixture", catalog_digest="b" * 64, coverage_state="authoritative",
            approved_at=timezone.now(), approved_by=self.source, is_current=True,
        )
        ProductReleaseDefinition.objects.create(product_release=release, qc_definition=definition, is_primary=True)
        unit = ProductUnit.objects.create(product_release=release, product_unit_code="unit-01", provenance="fixture")
        delivery = Delivery.objects.create(user=self.source, filename="fixture.zip", size_bytes=1, date_submitted=timezone.now())
        job = Job.objects.create(delivery=delivery, product_ident=definition.product_ident, product_description="Fixture", job_status="ok", product_release=release, qc_definition=definition, input_sha256="c" * 64)
        submission = DeliverySubmission.objects.create(
            delivery=delivery, job=job, product_release=release, product_unit=unit,
            product_unit_code=unit.product_unit_code, verified_product_unit_code=unit.product_unit_code,
            submitted_by=self.source, submitted_by_username=self.source.username,
            request_channel="browser", publication_state="published", published_at=timezone.now(),
            artifact_key="published/fixture", artifact_digest="d" * 64, input_digest="c" * 64,
            review_state="accepted", review_version=1,
        )
        SubmissionReviewEvent.objects.create(submission=submission, version=1, decision="approved", actor=self.source, actor_username=self.source.username)
        conflict = SubmissionConflict.objects.create(product_unit=unit, state="resolved", version=1, selected_submission=submission, opened_at=timezone.now(), resolved_at=timezone.now(), resolved_by=self.source)
        SubmissionConflictEvent.objects.create(conflict=conflict, version=1, event_type="resolved", selected_submission=submission, actor=self.source)
        return product, delivery, job, submission

    def empty_business(self):
        # Test-only disposable data removal deliberately bypasses retention. The
        # production transfer engine never deletes or empties a target table.
        from qc_tool.database.transfers.records import RESOURCE_FIELDS
        for model, _fields in reversed(tuple(RESOURCE_FIELDS.values())):
            model.objects.all()._raw_delete("default")

    def test_application_merge_preserves_receipt_uuid_timestamps_and_history(self):
        _product, _delivery, _job, submission = self.fixture_graph()
        payload = export_records("application")
        original = deepcopy(payload["records"])
        self.assertTrue(plan_records(payload)["blockers"])
        self.empty_business()
        mappings = {str(user.pk): user.pk for user in (self.source, self.other)}
        plan = plan_records(payload, mappings)
        self.assertFalse(plan["blockers"])
        result = apply_records(payload, plan)
        self.assertEqual(result["created_counts"]["submissions"], 1)
        self.assertEqual(verify_records(payload, result)["verified_counts"]["submissions"], 1)
        exported = export_records("application")["records"]
        self.assertEqual(exported["submissions"][0]["submission_uuid"], original["submissions"][0]["submission_uuid"])
        self.assertEqual(exported["submissions"][0]["requested_at"], original["submissions"][0]["requested_at"])
        self.assertEqual(exported["submissions"][0]["artifact_digest"], original["submissions"][0]["artifact_digest"])
        self.assertEqual(exported["jobs"][0]["date_created"], original["jobs"][0]["date_created"])
        self.assertEqual(exported["deliveries"][0]["date_uploaded"], original["deliveries"][0]["date_uploaded"])
        self.assertEqual(exported["definitions"][0]["document"], original["definitions"][0]["document"])
        restored = DeliverySubmission.objects.get(pk=submission.pk)
        self.assertEqual(restored.review_events.get().decision, "approved")
        self.assertEqual(restored.selected_for_conflicts.get().events.get().selected_submission_id, submission.pk)
        with self.assertRaises(TransferError):
            apply_records(payload, plan)

    def test_missing_dependency_and_cross_unit_history_are_blocked(self):
        self.fixture_graph()
        payload = export_records("application")
        changed = deepcopy(payload)
        changed["records"]["units"] = []
        with self.assertRaisesMessage(TransferError, "missing dependency"):
            validate_records(changed)
        changed = deepcopy(payload)
        changed["records"]["submissions"][0]["product_unit_code"] = "different-unit"
        with self.assertRaisesMessage(TransferError, "inconsistent"):
            validate_records(changed)

    def test_active_jobs_and_incomplete_publications_are_never_imported(self):
        _product, delivery, job, _submission = self.fixture_graph()
        payload = export_records("application")
        payload["records"]["jobs"][0]["job_status"] = "waiting"
        with self.assertRaisesMessage(TransferError, "Active or unknown"):
            validate_records(payload)
        payload["records"]["jobs"][0]["job_status"] = "ok"
        payload["records"]["submissions"][0]["publication_state"] = "publishing"
        with self.assertRaisesMessage(TransferError, "Incomplete publication"):
            validate_records(payload)

    @override_settings(QC_TOOL_TRANSFER_MAX_RECORDS=1)
    def test_configured_record_limit_is_enforced(self):
        with patch("qc_tool.database.transfers.records.json_value") as serialize, \
                patch("qc_tool.database.transfers.records._validated_field") as validate:
            with self.assertRaisesMessage(TransferError, "record limit"):
                export_records("accounts")
        serialize.assert_not_called()
        validate.assert_not_called()

    def test_sql_counts_match_serialized_graph_and_all_referenced_accounts(self):
        product, _delivery, job, _submission = self.fixture_graph()
        requester = get_user_model().objects.create_user("separate-requester")
        get_user_model().objects.create_user("unreferenced-account")
        Product.objects.filter(pk=product.pk).update(ready_by=self.other)
        Job.objects.filter(pk=job.pk).update(requested_by=requester)
        for include_unreferenced in (False, True):
            with self.subTest(include_unreferenced=include_unreferenced):
                counts = export_record_counts("application", include_unreferenced_accounts=include_unreferenced)
                payload = export_records("application", include_unreferenced_accounts=include_unreferenced)
                self.assertEqual(counts, {"accounts": len(payload["accounts"]),
                                         **{name: len(rows) for name, rows in payload["records"].items()}})
                self.assertEqual(counts["accounts"], 4 if include_unreferenced else 3)

    def test_sql_counts_keep_selected_accounts_and_reject_missing_selection(self):
        self.assertEqual(export_record_counts("accounts", [self.other.pk]), {"accounts": 1})
        with self.assertRaisesMessage(TransferError, "no longer exists"):
            export_record_counts("accounts", [self.other.pk, 999999])

    @override_settings(QC_TOOL_TRANSFER_MAX_RECORDS=1)
    def test_current_application_snapshot_is_independent_of_portable_package_limit(self):
        self.fixture_graph()
        snapshot = snapshot_current_application()
        self.assertEqual({row["username"] for row in snapshot["accounts"]},
                         {self.source.username, self.other.username})
        self.assertEqual(len(snapshot["records"]["submissions"]), 1)
        self.assertEqual(len(snapshot["records"]["review_events"]), 1)
        self.assertEqual(len(snapshot["records"]["conflict_events"]), 1)
        for portable_operation in (lambda: export_records("application"),
                                   lambda: validate_records(snapshot),
                                   lambda: plan_records(snapshot)):
            with self.subTest(operation=portable_operation):
                with self.assertRaisesMessage(TransferError, "record limit"):
                    portable_operation()

    @override_settings(QC_TOOL_TRANSFER_MAX_RECORDS=1)
    def test_current_application_snapshot_still_rejects_invalid_persisted_business_graph(self):
        self.fixture_graph()
        Job.objects.update(job_status="waiting")
        with self.assertRaisesMessage(TransferError, "Active or unknown"):
            snapshot_current_application()

    @override_settings(QC_TOOL_TRANSFER_MAX_RECORDS=1)
    def test_unbounded_graph_validation_keeps_field_and_foreign_key_checks(self):
        self.fixture_graph()
        snapshot = snapshot_current_application()
        missing = deepcopy(snapshot)
        missing["records"]["units"] = []
        with self.assertRaisesMessage(TransferError, "missing dependency"):
            validate_records(missing, enforce_package_limits=False)
        invalid = deepcopy(snapshot)
        invalid["accounts"][0]["email"] = "invalid-nonblank-email"
        with self.assertRaisesMessage(TransferError, "email violates its field contract"):
            validate_records(invalid, enforce_package_limits=False)

    def test_duplicate_unique_and_revision_cycle_are_preflight_blockers(self):
        self.fixture_graph()
        payload = export_records("application")
        changed = deepcopy(payload)
        duplicate = deepcopy(changed["records"]["products"][0])
        duplicate["id"] += 1000
        changed["records"]["products"].append(duplicate)
        with self.assertRaisesMessage(TransferError, "conflicting unique"):
            validate_records(changed)
        changed = deepcopy(payload)
        changed["records"]["releases"][0]["supersedes_id"] = changed["records"]["releases"][0]["id"]
        with self.assertRaisesMessage(TransferError, "increase revision"):
            validate_records(changed)

    def test_application_mapping_must_preserve_artifact_username(self):
        self.fixture_graph()
        payload = export_records("application")
        self.empty_business()
        mappings = {str(self.source.pk): self.other.pk, str(self.other.pk): self.source.pk}
        plan = plan_records(payload, mappings)
        self.assertTrue(any("preserve usernames" in item for item in plan["blockers"]))

    def test_application_preserves_full_datetime_precision(self):
        self.fixture_graph()
        payload = export_records("application")
        self.assertEqual(payload["records"]["submissions"][0]["requested_at"], DeliverySubmission.objects.get().requested_at.isoformat())
        self.assertEqual(payload["accounts"][0]["date_joined"], self.source.date_joined.isoformat())

    def test_verifier_detects_committed_sql_tampering(self):
        self.fixture_graph()
        payload = export_records("application")
        self.empty_business()
        plan = plan_records(payload, {str(user.pk): user.pk for user in (self.source, self.other)})
        result = apply_records(payload, plan)
        self.assertTrue(verify_records(payload, result))
        Product.objects.update(name="Tampered after commit")
        with self.assertRaisesMessage(TransferError, "differ from their receipt"):
            verify_records(payload, result)

    def test_verifier_detects_imported_account_activation(self):
        payload = export_records("accounts", [self.source.pk])
        payload["accounts"][0]["username"] = "verify-account"
        plan = plan_records(payload)
        result = apply_records(payload, plan)
        self.assertTrue(verify_records(payload, result))
        get_user_model().objects.filter(pk=result["user_mappings"][str(self.source.pk)]).update(is_active=True)
        with self.assertRaisesMessage(TransferError, "inactive access boundary"):
            verify_records(payload, result)

    def test_atomic_failure_rolls_back_all_created_records(self):
        self.fixture_graph()
        payload = export_records("application")
        self.empty_business()
        plan = plan_records(payload, {str(user.pk): user.pk for user in (self.source, self.other)})
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                apply_records(payload, plan)
                raise RuntimeError("Injected failure before receipt commit")
        self.assertFalse(Product.objects.exists())
        self.assertFalse(DeliverySubmission.objects.exists())
