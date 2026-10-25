"""Application transfer with real publication files on disposable test storage."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from qc_tool.common import CONFIG, compose_job_dir
from qc_tool.database.models import TransferReceipt
from qc_tool.database.transfers import service, store
from qc_tool.database.transfers.artifacts import ArtifactRestorePlan, collect_artifacts
from qc_tool.database.transfers.records import RESOURCE_FIELDS, export_records, validate_records
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.dashboard.models import (
    Delivery, DeliverySubmission, Job, Product, ProductRelease,
    ProductReleaseDefinition, ProductUnit, QcDefinition, SubmissionReviewEvent,
    SubmissionConflict, SubmissionConflictEvent,
)
from qc_tool.frontend.dashboard.services import maintenance
from qc_tool.frontend.dashboard.services.maintenance.operations import active_operation
from qc_tool.frontend.dashboard.services.catalog.manifest.definitions import parse_definition_snapshot
from qc_tool.frontend.dashboard.services.submissions.artifacts import open_submission_file
from qc_tool.frontend.dashboard.services.submissions.contracts import ReservedSubmission
from qc_tool.frontend.dashboard.services.submissions.publication import publish_reserved_submission


class ApplicationTransferIntegrationTests(TestCase):
    def test_record_export_includes_every_referenced_actor_but_not_unrelated_users(self):
        User = get_user_model()
        actors = {role: User.objects.create_user(role, email=f"{role}@example.test")
                  for role in ("readiness-owner", "release-approver", "job-requester", "conflict-resolver")}
        unrelated = User.objects.create_user("unrelated-profile", email="unrelated@example.test")
        Product.objects.update(ready_at=timezone.now(), ready_scope_digest="c" * 64,
                               ready_by=actors["readiness-owner"], ready_by_username="readiness-owner")
        ProductRelease.objects.update(approved_by=actors["release-approver"])
        Job.objects.update(requested_by=actors["job-requester"], requested_by_username="job-requester")
        SubmissionConflict.objects.update(resolved_by=actors["conflict-resolver"], resolved_by_username="conflict-resolver")

        payload = export_records("application", include_unreferenced_accounts=False)

        # The original operator is now referenced only by immutable review and
        # conflict events. Its profile must remain without rewriting that history.
        self.assertEqual({row["username"] for row in payload["accounts"]},
                         {self.owner.username, self.actor.username, *actors})
        self.assertNotIn(unrelated.pk, payload["selection"]["user_ids"])
        # Native activation still validates all current profiles, and Users
        # exports still offer accounts with no QC history of their own.
        from qc_tool.database.transfers.records import snapshot_current_application
        self.assertIn(unrelated.pk, snapshot_current_application()["selection"]["user_ids"])
        self.assertIn(unrelated.pk, export_records("accounts")["selection"]["user_ids"])

    def test_record_export_service_keeps_unrelated_profiles_in_the_users_area(self):
        get_user_model().objects.create_user("profiles-only", email="profiles@example.test")
        records = service.export_preview({"profile": "application", "user_ids": [], "include_files": True}, self.actor)
        users = service.export_preview({"profile": "accounts", "user_ids": []}, self.actor)
        self.assertEqual(records["counts"]["accounts"], 2)
        self.assertEqual(users["counts"]["accounts"], 3)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        configured = override_settings(QC_TOOL_MAINTENANCE_DIR=str(self.root / "maintenance"),
            QC_TOOL_TRANSFER_DIR=str(self.root / "transfers"), MAINTENANCE_MODE=False)
        configured.enable()
        self.addCleanup(configured.disable)
        self.source_config = self.configuration("source")
        self.target_config = self.configuration("target")
        self.configured = patch.dict(CONFIG, self.source_config)
        self.configured.start()
        self.addCleanup(self.configured.stop)
        launching = patch.object(service, "_launch")
        launching.start()
        self.addCleanup(launching.stop)
        self.actor = get_user_model().objects.create_superuser("operator", "operator@example.test", "test-password")
        self.owner = get_user_model().objects.create_user("delivery-owner", "owner@example.test", "owner-password")
        self.generation = maintenance.enable(self.actor, 0)["generation"]
        self.assertEqual(maintenance.advance(self.generation)["phase"], "ready")
        self.make_graph()

    def configuration(self, prefix):
        base = self.root / prefix
        result = {key: base / name for key, name in (("work_dir", "work"), ("incoming_dir", "incoming"),
                                                    ("submission_dir", "submissions"), ("boundary_dir", "boundaries"))}
        for path in result.values():
            path.mkdir(parents=True)
        result["product_dirs"] = []
        return result

    def make_graph(self):
        self.specification = json.dumps({"description": "Transfer integration product", "steps": [{
            "check_ident": "qc_tool.vector.naming", "required": True,
            "parameters": {"reference_year": "2026", "aoi_codes": ["CZ"]},
        }]}, indent=4).encode() + b"\n\n"
        snapshot = parse_definition_snapshot("transfer-product", self.specification, source_path="upload:transfer-product.json")
        uploaded = self.source_config["work_dir"] / "product_definitions"
        versions = uploaded / ".versions" / "transfer-product"
        versions.mkdir(parents=True)
        (versions / (snapshot.digest + ".json")).write_bytes(self.specification)
        (uploaded / ".state").mkdir()
        (uploaded / ".state" / "transfer-product.json").write_text(json.dumps({"active": True, "digest": snapshot.digest}))
        product = Product.objects.create(ident="transfer-product", name="Transfer integration product")
        definition = QcDefinition.objects.create(product_ident=snapshot.product_ident, digest=snapshot.digest,
            description=snapshot.description, document=snapshot.document, source_path=snapshot.source_path)
        release = ProductRelease.objects.create(product=product, release_key="transfer-2026", revision=1,
            description="Transfer integration release", catalog_digest="b" * 64, coverage_state="authoritative",
            approved_at=timezone.now(), approved_by=self.actor, is_current=True)
        ProductReleaseDefinition.objects.create(product_release=release, qc_definition=definition, is_primary=True)
        unit = ProductUnit.objects.create(product_release=release, product_unit_code="CZ", provenance="fixture")
        self.input_bytes = b"retained original delivery ZIP bytes"
        self.input_digest = hashlib.sha256(self.input_bytes).hexdigest()
        incoming = self.source_config["incoming_dir"] / self.owner.username
        incoming.mkdir()
        (incoming / "fixture.zip").write_bytes(self.input_bytes)
        delivery = Delivery.objects.create(user=self.owner, filename="fixture.zip", size_bytes=len(self.input_bytes),
            content_sha256=self.input_digest, date_submitted=timezone.now())
        job = Job.objects.create(delivery=delivery, product_ident=definition.product_ident, product_description=definition.description,
            job_status="ok", product_release=release, qc_definition=definition, input_sha256=self.input_digest,
            requested_by=self.owner, requested_by_username=self.owner.username, request_source="browser")
        job_dir = compose_job_dir(job.job_uuid)
        job_dir.mkdir()
        (job_dir / "output.d").mkdir()
        (job_dir / "output.d" / "attachment.txt").write_bytes(b"verified attachment")
        (job_dir / "report.pdf").write_bytes(b"%PDF-1.4 integration report")
        (job_dir / "result.json").write_text(json.dumps({"report_filename": "report.pdf"}))
        (job_dir / "transfer-product.json").write_bytes(self.specification)
        (job_dir / "job.log").write_bytes(b"immutable published QC log")
        self.submission = DeliverySubmission.objects.create(delivery=delivery,
            job=job, product_release=release, product_unit=unit, product_unit_code=unit.product_unit_code,
            verified_product_unit_code=unit.product_unit_code, submitted_by=self.owner, submitted_by_username=self.owner.username,
            request_channel="browser", input_digest=self.input_digest, review_state="accepted", review_version=1)
        reserved = ReservedSubmission(submission_uuid=self.submission.pk, delivery_id=delivery.pk, job_uuid=job.pk,
            product_release_id=release.pk, product_unit_id=unit.pk, release_key=release.release_key,
            product_unit_code=unit.product_unit_code, verified_product_unit_code=unit.product_unit_code,
            username=self.owner.username, filename=delivery.filename, is_s3=False,
            expected_input_digest=self.input_digest, requested_at_iso=self.submission.requested_at.isoformat(), already_existed=False)
        receipt = publish_reserved_submission(reserved, submission_root=self.source_config["submission_dir"], media_root=self.source_config["incoming_dir"])
        self.submission.publication_state = "published"
        self.submission.published_at = timezone.now()
        self.submission.artifact_key = receipt.artifact_key
        self.submission.artifact_digest = receipt.artifact_digest
        self.submission.save()
        SubmissionReviewEvent.objects.create(submission=self.submission, version=1, decision="approved", actor=self.actor,
            actor_username=self.actor.username)
        conflict = SubmissionConflict.objects.create(product_unit=unit, state="resolved", version=1, selected_submission=self.submission,
            opened_at=timezone.now(), resolved_at=timezone.now(), resolved_by=self.actor)
        SubmissionConflictEvent.objects.create(conflict=conflict, version=1, event_type="resolved", selected_submission=self.submission, actor=self.actor)
        self.original_records = deepcopy(export_records("application")["records"])
        self.original_manifest = (self.source_config["submission_dir"] / receipt.artifact_key / "submission-manifest.json").read_bytes()

    def prepare_import(self, *, reuse_upload=False, initialize_target=None, plan_only=False):
        selection = {"profile": "application", "user_ids": [], "include_files": True}
        preview = service.export_preview(selection, self.actor)
        operation = service.create_export(selection, self.actor, preview["review_hash"], self.generation)
        self.assertEqual(service.run_operation(operation["id"])["status"], "completed")
        stream, _ = service.download_operation(operation["id"], self.actor)
        with stream:
            data = stream.read()
        # This deliberate removal is limited to the fresh disposable test DB.
        # The production transfer runner never empties or replaces a target.
        for model, _fields in reversed(tuple(RESOURCE_FIELDS.values())):
            model.objects.all()._raw_delete("default")
        CONFIG.update(self.target_config)
        if initialize_target is not None:
            # Simulate a genuinely separate occupied destination namespace in
            # this disposable test DB; production never removes source receipts.
            TransferReceipt.objects.all().delete()
            initialize_target()
        if reuse_upload:
            target = self.target_config["incoming_dir"] / self.owner.username
            target.mkdir()
            (target / "fixture.zip").write_bytes(self.input_bytes)
        staged = service.stage_import(SimpleUploadedFile("application.zip", data), self.actor)
        mappings = {str(user.pk): user.pk for user in (self.actor, self.owner)}
        plan = service.plan_import(staged["id"], self.actor, mappings)
        if plan_only:
            return staged, plan
        self.assertTrue(plan["can_apply"], plan["blockers"])
        return service.start_import(staged["id"], self.actor, plan["plan_hash"], self.generation, True)

    def assert_restored(self):
        # Additive restoration allocates local integer identities even when the
        # disposable target is empty; all other source values remain intact.
        receipt = TransferReceipt.objects.filter(profile="application").latest("pk")
        identities = receipt.summary["identity_map"]
        resources = {model: name for name, (model, _fields) in RESOURCE_FIELDS.items()}
        resources[get_user_model()] = "accounts"
        expected = deepcopy(self.original_records)
        for name, (model, fields) in RESOURCE_FIELDS.items():
            for row in expected[name]:
                primary = model._meta.pk.attname
                row[primary] = identities[name][str(row[primary])]
                for field in model._meta.concrete_fields:
                    if field.is_relation and field.attname in fields and row[field.attname] is not None:
                        row[field.attname] = identities[resources[field.remote_field.model]][str(row[field.attname])]
            expected[name].sort(key=lambda row: str(row[model._meta.pk.attname]))
        actual = export_records("application")["records"]
        for name, (model, _fields) in RESOURCE_FIELDS.items():
            actual[name].sort(key=lambda row: str(row[model._meta.pk.attname]))
        self.assertEqual(actual, expected)
        restored = DeliverySubmission.objects.get(pk=self.submission.pk)
        self.assertEqual(restored.review_events.get().decision, "approved")
        self.assertEqual(restored.selected_for_conflicts.get().events.get().selected_submission_id, restored.pk)
        with open_submission_file(restored, "input.d/fixture.zip") as stream:
            self.assertEqual(stream.read(), self.input_bytes)
        with open_submission_file(restored, "output.d/attachment.txt") as stream:
            self.assertEqual(stream.read(), b"verified attachment")
        directory = self.target_config["submission_dir"] / restored.artifact_key
        self.assertEqual((directory / "submission-manifest.json").read_bytes(), self.original_manifest)
        self.assertEqual((directory / "job.log").read_bytes(), b"immutable published QC log")
        self.assertTrue(TransferReceipt.objects.filter(profile="application").exists())

    def test_full_service_roundtrip_preserves_graph_and_publication_downloads(self):
        operation = self.prepare_import()
        self.assertEqual(service.run_operation(operation["id"])["status"], "completed")
        self.assert_restored()

    def test_database_failure_rolls_back_only_new_files_and_retry_restores(self):
        operation = self.prepare_import(reuse_upload=True)
        with patch.object(TransferReceipt.objects, "create", side_effect=RuntimeError("Injected precommit receipt failure")):
            with self.assertRaises(service.TransferError):
                service.run_operation(operation["id"])
        self.assertFalse(Product.objects.exists())
        self.assertFalse(DeliverySubmission.objects.exists())
        self.assertEqual((self.target_config["incoming_dir"] / self.owner.username / "fixture.zip").read_bytes(), self.input_bytes)
        self.assertFalse((self.target_config["submission_dir"] / self.submission.artifact_key).exists())
        service.recover_operation(operation["id"], self.actor, "retry")
        self.assertEqual(service.run_operation(operation["id"])["status"], "completed")
        self.assert_restored()

    def test_retry_revokes_previous_rollback_cancellation_before_republishing(self):
        operation = self.prepare_import()
        with patch.object(TransferReceipt.objects, "create", side_effect=RuntimeError("Injected precommit receipt failure")):
            with self.assertRaises(service.TransferError):
                service.run_operation(operation["id"])
        self.assertTrue(store.read_operation(operation["id"])["safe_to_cancel"])
        self.assertFalse((self.target_config["submission_dir"] / self.submission.artifact_key).exists())
        service.recover_operation(operation["id"], self.actor, "retry")

        restore_artifacts = ArtifactRestorePlan.apply

        def interrupted_after_publication(restore, *args, **kwargs):
            journal = store.read_operation(operation["id"])
            self.assertTrue(journal["files_started"])
            self.assertFalse(journal["safe_to_cancel"])
            restore_artifacts(restore, *args, **kwargs)
            # Real immutable files have been published again, before SQL is
            # attempted. Process death bypasses the ordinary rollback handler.
            self.assertTrue((self.target_config["submission_dir"] / self.submission.artifact_key).is_dir())
            raise KeyboardInterrupt

        with patch.object(ArtifactRestorePlan, "apply", autospec=True, side_effect=interrupted_after_publication):
            with self.assertRaises(KeyboardInterrupt):
                service.run_operation(operation["id"])
        self.assertFalse(Product.objects.exists())
        self.assertFalse(TransferReceipt.objects.filter(profile="application").exists())
        self.assertFalse(service.get_operation(operation["id"], self.actor)["cancellable"])
        with self.assertRaisesMessage(service.TransferError, "may have published files"):
            service.recover_operation(operation["id"], self.actor, "cancel")
        self.assertEqual(active_operation()["operation_id"], operation["id"])
        self.assertTrue((store.operation_dir(operation["id"]) / "package.zip").exists())
        self.assertTrue((self.target_config["submission_dir"] / self.submission.artifact_key).is_dir())

        service.recover_operation(operation["id"], self.actor, "retry")
        self.assertEqual(service.run_operation(operation["id"])["status"], "completed")
        self.assert_restored()

    def test_lost_postcommit_ack_recovers_without_reinsertion_or_file_removal(self):
        operation = self.prepare_import()
        real_save = store.save_operation

        def lost_ack(value):
            if value["status"] == "completed":
                raise OSError("Injected postcommit acknowledgment loss")
            return real_save(value)

        with patch.object(store, "save_operation", side_effect=lost_ack):
            with self.assertRaises(service.TransferError):
                service.run_operation(operation["id"])
        self.assert_restored()
        service.recover_operation(operation["id"], self.actor, "retry")
        self.assertEqual(service.run_operation(operation["id"])["status"], "completed")
        self.assert_restored()
        self.assertEqual(TransferReceipt.objects.filter(profile="application").count(), 1)

    def test_occupied_target_rekeys_published_graph_keeps_zip_and_reexports_idempotently(self):
        UserProductGrant.objects.create(user=self.owner, product_ident="transfer-product")
        original = self.original_records
        source_delivery = original["deliveries"][0]["id"]
        source_release = original["releases"][0]["id"]
        source_unit = original["units"][0]["id"]
        job_uuid = original["jobs"][0]["job_uuid"]
        retained = {}

        def populate():
            product = Product.objects.create(
                pk=original["products"][0]["id"], ident="existing-local-product", name="Already live",
            )
            release = ProductRelease.objects.create(
                pk=source_release, product=product, release_key="local-release", revision=1,
                catalog_digest="c" * 64,
            )
            ProductUnit.objects.create(
                pk=source_unit, product_release=release, product_unit_code="de", provenance="local fixture",
            )
            other_bytes = b"preexisting unrelated local ZIP"
            owner_root = self.target_config["incoming_dir"] / self.actor.username
            owner_root.mkdir()
            (owner_root / "local.zip").write_bytes(other_bytes)
            Delivery.objects.create(
                pk=source_delivery, user=self.actor, filename="local.zip", size_bytes=len(other_bytes),
                content_sha256=hashlib.sha256(other_bytes).hexdigest(), product_ident=product.ident,
            )
            retained["records"] = {name: list(model.objects.values()) for name, (model, _fields) in RESOURCE_FIELDS.items()}
            retained["zip"] = owner_root / "local.zip"
            retained["zip_bytes"] = other_bytes

        operation = self.prepare_import(reuse_upload=True, initialize_target=populate)
        retained_zip = self.target_config["incoming_dir"] / self.owner.username / "fixture.zip"
        retained_inode = retained_zip.stat().st_ino
        plan = store.read_operation(operation["id"])["plan"]
        self.assertEqual(plan["mode"], "additive")
        self.assertEqual(plan["delivery_files"][0]["file_status"], "retained_verified")
        completed = service.run_operation(operation["id"])
        self.assertEqual(completed["status"], "completed")
        imported = Job.objects.get(pk=job_uuid)
        submission = DeliverySubmission.objects.get(pk=self.submission.pk)
        self.assertNotEqual(imported.delivery_id, source_delivery)
        self.assertNotEqual(imported.product_release_id, source_release)
        self.assertNotEqual(submission.product_unit_id, source_unit)
        self.assertEqual(submission.delivery_id, imported.delivery_id)
        self.assertEqual(submission.job_id, imported.pk)
        self.assertEqual(retained_zip.stat().st_ino, retained_inode)
        self.assertEqual(retained_zip.read_bytes(), self.input_bytes)
        self.assertEqual(retained["zip"].read_bytes(), retained["zip_bytes"])
        for name, (model, _fields) in RESOURCE_FIELDS.items():
            for row in retained["records"][name]:
                actual = model.objects.filter(pk=row[model._meta.pk.attname]).values().get()
                self.assertEqual(actual, row)
        manifest = self.target_config["submission_dir"] / submission.artifact_key / "submission-manifest.json"
        self.assertEqual(manifest.read_bytes(), self.original_manifest)
        self.client.force_login(self.owner)
        with override_settings(MEDIA_ROOT=str(self.target_config["incoming_dir"])):
            response = self.client.get(reverse("job_input_zip", args=(imported.pk,)))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), self.input_bytes)
        # Export the merged graph again: original publication source IDs remain
        # in provenance while local FKs have their newly allocated identities.
        exported = validate_records(export_records("application"))
        self.assertEqual(exported["format"], 2)
        inventory = collect_artifacts(exported)
        self.assertTrue(inventory.sources)
        namespace = exported["provenance"]["publications"][str(submission.pk)]
        self.assertEqual(namespace["delivery_id"], source_delivery)
        self.assertEqual(namespace["product_release_id"], source_release)
        self.assertEqual(namespace["product_unit_id"], source_unit)
        selection = {"profile": "application", "user_ids": [], "include_files": True}
        preview = service.export_preview(selection, self.actor)
        second_export = service.create_export(selection, self.actor, preview["review_hash"], self.generation)
        self.assertEqual(service.run_operation(second_export["id"])["status"], "completed")
        stream, _metadata = service.download_operation(second_export["id"], self.actor)
        with stream:
            package = stream.read()
        staged = service.stage_import(SimpleUploadedFile("merged.zip", package), self.actor)
        mappings = {str(user.pk): user.pk for user in (self.actor, self.owner)}
        before_counts = {name: model.objects.count() for name, (model, _fields) in RESOURCE_FIELDS.items()}
        second_plan = service.plan_import(staged["id"], self.actor, mappings)
        self.assertTrue(second_plan["can_apply"], second_plan["blockers"])
        second = service.start_import(staged["id"], self.actor, second_plan["plan_hash"], self.generation, True)
        self.assertEqual(service.run_operation(second["id"])["status"], "completed")
        self.assertEqual({name: model.objects.count() for name, (model, _fields) in RESOURCE_FIELDS.items()}, before_counts)
        self.assertEqual(manifest.read_bytes(), self.original_manifest)

    def test_conflicting_retained_zip_can_skip_connected_history_without_overwriting(self):
        conflicting = b"x" * len(self.input_bytes)
        path = self.target_config["incoming_dir"] / self.owner.username / "fixture.zip"

        def populate():
            path.parent.mkdir()
            path.write_bytes(conflicting)

        staged, plan = self.prepare_import(initialize_target=populate, plan_only=True)
        source_id = self.original_records["deliveries"][0]["id"]
        key = "deliveries:" + str(source_id)
        self.assertFalse(plan["can_apply"])
        self.assertTrue(any(row["key"] == key for row in plan["record_conflicts"]))
        self.assertEqual(path.read_bytes(), conflicting)
        mappings = {str(user.pk): user.pk for user in (self.actor, self.owner)}
        reviewed = service.plan_import(staged["id"], self.actor, mappings, {key: "skip"})
        self.assertTrue(reviewed["can_apply"], reviewed["blockers"])
        queued = service.start_import(staged["id"], self.actor, reviewed["plan_hash"], self.generation, True)
        self.assertEqual(service.run_operation(queued["id"])["status"], "completed")
        self.assertTrue(Product.objects.filter(ident="transfer-product").exists())
        for model in (Delivery, Job, DeliverySubmission, SubmissionReviewEvent, SubmissionConflict, SubmissionConflictEvent):
            self.assertFalse(model.objects.exists(), model._meta.label)
        self.assertEqual(path.read_bytes(), conflicting)
        self.assertFalse((self.target_config["submission_dir"] / self.submission.artifact_key).exists())

    def test_conflicting_retained_job_report_can_skip_job_and_publication_history(self):
        identifier = self.original_records["jobs"][0]["job_uuid"]
        directory = self.target_config["work_dir"] / ("job_" + identifier.replace("-", ""))

        def populate():
            directory.mkdir()
            (directory / "result.json").write_bytes(b"preexisting different local result")

        staged, plan = self.prepare_import(reuse_upload=True, initialize_target=populate, plan_only=True)
        key = "jobs:" + identifier
        self.assertFalse(plan["can_apply"])
        self.assertTrue(any(row["key"] == key for row in plan["record_conflicts"]))
        mappings = {str(user.pk): user.pk for user in (self.actor, self.owner)}
        reviewed = service.plan_import(staged["id"], self.actor, mappings, {key: "skip"})
        self.assertTrue(reviewed["can_apply"], reviewed["blockers"])
        queued = service.start_import(staged["id"], self.actor, reviewed["plan_hash"], self.generation, True)
        self.assertEqual(service.run_operation(queued["id"])["status"], "completed")
        self.assertEqual(Delivery.objects.count(), 1)
        for model in (Job, DeliverySubmission, SubmissionReviewEvent, SubmissionConflict, SubmissionConflictEvent):
            self.assertFalse(model.objects.exists(), model._meta.label)
        self.assertEqual((directory / "result.json").read_bytes(), b"preexisting different local result")
