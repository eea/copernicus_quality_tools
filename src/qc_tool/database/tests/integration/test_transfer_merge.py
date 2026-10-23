"""Insert-only graph merging on populated disposable application databases."""

from copy import deepcopy
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from qc_tool.database.models import TransferReceipt
from qc_tool.database.transfers.contracts import TransferError
from qc_tool.database.transfers.provenance import ensure_namespace, load_identity_index
from qc_tool.database.transfers.records import (
    RESOURCE_FIELDS, apply_records, export_records, plan_records, verify_records,
)
from qc_tool.frontend.dashboard.models import (
    Delivery, DeliverySubmission, Job, Product, ProductRelease, ProductReleaseDefinition,
    ProductUnit, QcDefinition, S3Info, SubmissionConflict, SubmissionConflictEvent,
    SubmissionReviewEvent,
)


class AdditiveTransferRecordTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.actor = User.objects.create_superuser("merge-admin", "admin@example.test", "password")
        self.owner = User.objects.create_user("merge-owner", "owner@example.test", "password")
        self.source_graph = self.graph("incoming", self.owner)
        self.source = export_records("application")
        self.clear_business()
        self.target_graph = self.graph("existing", self.actor)
        self.mappings = {row["key"]: User.objects.get(username=row["username"]).pk for row in self.source["accounts"]}

    def graph(self, prefix, owner, *, job_uuid=None):
        def key(name):
            original = getattr(self, "source_graph", {}).get(name)
            return {"pk": original.pk} if original is not None else {}

        product = Product.objects.create(**key("product"), ident=prefix + "-product", name=prefix + " product")
        definition = QcDefinition.objects.create(**key("definition"), product_ident=product.ident,
            digest=("a" if prefix == "incoming" else "e") * 64, description=prefix,
            document={"fixture": prefix}, source_path=prefix + ".json")
        release = ProductRelease.objects.create(**key("release"), product=product, release_key=prefix + "-stream", revision=1,
            description=prefix, catalog_digest=("b" if prefix == "incoming" else "f") * 64,
            coverage_state="authoritative", approved_at=timezone.now(), approved_by=self.actor, is_current=True)
        link = ProductReleaseDefinition.objects.create(**key("link"), product_release=release, qc_definition=definition, is_primary=True)
        unit = ProductUnit.objects.create(**key("unit"), product_release=release, product_unit_code="CZ", provenance=prefix)
        remote = S3Info.objects.create(**key("remote"), host=prefix + ".example.test", bucketname=prefix, key_prefix="original")
        delivery = Delivery.objects.create(**key("delivery"), user=owner, filename=prefix + ".zip", size_bytes=7,
            content_sha256="c" * 64, date_submitted=timezone.now())
        job = Job.objects.create(job_uuid=job_uuid or uuid4(), delivery=delivery, product_ident=product.ident,
            product_description=prefix, job_status="ok", product_release=release,
            qc_definition=definition, requested_by=owner, requested_by_username=owner.username,
            request_source="browser", input_sha256="c" * 64)
        submission = DeliverySubmission.objects.create(delivery=delivery, job=job,
            product_release=release, product_unit=unit, product_unit_code=unit.product_unit_code,
            verified_product_unit_code=unit.product_unit_code,
            submitted_by=owner, submitted_by_username=owner.username, request_channel="browser",
            publication_state="published", published_at=timezone.now(), artifact_key="published/" + prefix,
            artifact_digest="d" * 64, input_digest="c" * 64, review_state="accepted", review_version=1)
        review = SubmissionReviewEvent(**key("review"), submission=submission, version=1, decision="approved",
            actor=self.actor, actor_username=self.actor.username, created_at=timezone.now())
        review.save_base(raw=True, force_insert=True)
        conflict = SubmissionConflict.objects.create(**key("conflict"), product_unit=unit, state="resolved", version=1,
            selected_submission=submission, opened_at=timezone.now(), resolved_at=timezone.now(), resolved_by=self.actor)
        event = SubmissionConflictEvent(**key("event"), conflict=conflict, version=1,
            event_type="resolved", selected_submission=submission, actor=self.actor, created_at=timezone.now())
        event.save_base(raw=True, force_insert=True)
        return {"product": product, "definition": definition, "release": release,
                "link": link, "unit": unit, "remote": remote, "delivery": delivery,
                "job": job, "submission": submission, "review": review,
                "conflict": conflict, "event": event}

    def clear_business(self):
        # Only synthetic rows in Django's disposable test database are removed.
        for model, _fields in reversed(tuple(RESOURCE_FIELDS.values())):
            model.objects.all()._raw_delete("default")

    def record_receipt(self, result):
        return TransferReceipt.objects.create(package_id=uuid4(), package_sha256="a" * 64,
            operation_id=uuid4(), plan_sha256="b" * 64, profile="application", actor=self.actor,
            actor_name=self.actor.username, summary=result)

    def test_populated_target_integer_collisions_translate_every_foreign_key(self):
        original = {name: list(model.objects.values()) for name, (model, _fields) in RESOURCE_FIELDS.items()}
        plan = plan_records(self.source, self.mappings)
        self.assertFalse(plan["blockers"], plan["blockers"])
        result = apply_records(self.source, plan, self.actor)
        self.record_receipt(result)
        self.assertEqual(verify_records(self.source, result)["verified_counts"]["jobs"], 1)
        identities = result["identity_map"]
        for resource in ("products", "definitions", "releases", "units", "deliveries", "conflicts"):
            source_id = self.source["records"][resource][0]["id"]
            self.assertNotEqual(identities[resource][str(source_id)], source_id)
        incoming_job = Job.objects.get(pk=self.source_graph["job"].pk)
        incoming_submission = DeliverySubmission.objects.get(pk=self.source_graph["submission"].pk)
        self.assertEqual(incoming_job.delivery_id, identities["deliveries"][str(self.source_graph["delivery"].pk)])
        self.assertEqual(incoming_job.product_release_id, identities["releases"][str(self.source_graph["release"].pk)])
        self.assertEqual(incoming_job.qc_definition_id, identities["definitions"][str(self.source_graph["definition"].pk)])
        self.assertEqual(incoming_submission.product_unit_id, identities["units"][str(self.source_graph["unit"].pk)])
        self.assertEqual(incoming_submission.job_id, incoming_job.pk)
        self.assertEqual(incoming_submission.delivery_id, incoming_job.delivery_id)
        self.assertEqual(incoming_submission.review_events.get().actor_id, self.actor.pk)
        self.assertEqual(incoming_submission.selected_for_conflicts.get().events.get().selected_submission_id, incoming_submission.pk)
        for name, (model, _fields) in RESOURCE_FIELDS.items():
            pk = model._meta.pk.attname
            for row in original[name]:
                self.assertEqual(model.objects.values().get(**{pk: row[pk]}), row)

    def test_product_difference_requires_explicit_reuse_and_preserves_target_values(self):
        existing = self.target_graph["product"]
        Product.objects.filter(pk=existing.pk).update(ident=self.source_graph["product"].ident, name="Existing local name")
        key = f"products:{self.source_graph['product'].pk}"
        blocked = plan_records(self.source, self.mappings)
        self.assertTrue(blocked["blockers"])
        conflict = next(row for row in blocked["record_conflicts"] if row["key"] == key)
        self.assertEqual({choice["value"] for choice in conflict["choices"]}, {"reuse", "skip"})
        plan = plan_records(self.source, self.mappings, {key: "reuse"})
        self.assertFalse(plan["blockers"], plan["blockers"])
        result = apply_records(self.source, plan, self.actor)
        existing.refresh_from_db()
        self.assertEqual(existing.name, "Existing local name")
        self.assertEqual(result["actions"]["products"][str(self.source_graph["product"].pk)], "reuse")
        self.assertEqual(result["source_overrides"]["products"][str(self.source_graph["product"].pk)]["name"], "incoming product")
        verify_records(self.source, result)
        self.record_receipt(result)
        evidence = export_records("application")["provenance"]["source_records"]
        retained = next(row for row in evidence if row["resource"] == "products" and row["target_key"] == str(existing.pk))
        self.assertEqual(retained["record"]["name"], "incoming product")

    def test_skipping_parent_excludes_all_dependent_history_without_deleting_existing(self):
        key = f"products:{self.source_graph['product'].pk}"
        plan = plan_records(self.source, self.mappings, {key: "skip"})
        self.assertFalse(plan["blockers"], plan["blockers"])
        for name in ("releases", "release_definitions", "units", "jobs", "submissions", "conflicts", "conflict_events", "review_events"):
            self.assertEqual(set(plan["actions"][name].values()), {"skip"})
        result = apply_records(self.source, plan, self.actor)
        self.assertNotIn("jobs", result["created_counts"])
        self.assertNotIn(str(self.source_graph["job"].pk), result["identity_map"]["jobs"])
        self.assertTrue(Job.objects.filter(pk=self.target_graph["job"].pk).exists())
        self.assertFalse(Job.objects.filter(pk=self.source_graph["job"].pk).exists())
        verify_records(self.source, result)

    def test_same_count_edit_makes_review_stale_before_insertion(self):
        plan = plan_records(self.source, self.mappings)
        original_count = Delivery.objects.count()
        Delivery.objects.filter(pk=self.target_graph["delivery"].pk).update(filename="changed-existing.zip")
        with self.assertRaisesMessage(TransferError, "stale"):
            apply_records(self.source, plan, self.actor)
        self.assertEqual(Delivery.objects.count(), original_count)
        self.assertFalse(Job.objects.filter(pk=self.source_graph["job"].pk).exists())

    def test_conflicting_job_uuid_can_only_exclude_incoming_history(self):
        changed = deepcopy(self.source)
        old_uuid = changed["records"]["jobs"][0]["job_uuid"]
        collision_uuid = str(self.target_graph["job"].pk)
        changed["records"]["jobs"][0]["job_uuid"] = collision_uuid
        changed["records"]["submissions"][0]["job_id"] = collision_uuid
        blocked = plan_records(changed, self.mappings)
        conflict = next(row for row in blocked["record_conflicts"] if row["resource"] == "jobs")
        self.assertEqual([choice["value"] for choice in conflict["choices"]], ["skip"])
        self.assertTrue(blocked["blockers"])
        plan = plan_records(changed, self.mappings, {f"jobs:{collision_uuid}": "skip"})
        self.assertFalse(plan["blockers"], plan["blockers"])
        result = apply_records(changed, plan, self.actor)
        self.assertEqual(Job.objects.count(), 1)
        self.assertEqual(Job.objects.get().product_ident, "existing-product")
        self.assertFalse(Job.objects.filter(pk=old_uuid).exists())
        verify_records(changed, result)

    def test_distinct_packages_with_committed_origins_reuse_instead_of_duplicating(self):
        first = apply_records(self.source, plan_records(self.source, self.mappings), self.actor)
        self.record_receipt(first)
        counts = {name: model.objects.count() for name, (model, _fields) in RESOURCE_FIELDS.items()}
        second_package = deepcopy(self.source)
        second_package["created_at"] = timezone.now().isoformat()
        plan = plan_records(second_package, self.mappings)
        self.assertFalse(plan["blockers"], plan["blockers"])
        self.assertEqual({action for actions in plan["actions"].values() for action in actions.values()}, {"reuse"})
        result = apply_records(second_package, plan, self.actor)
        self.record_receipt(result)
        self.assertEqual(result["created_counts"], {})
        self.assertEqual({name: model.objects.count() for name, (model, _fields) in RESOURCE_FIELDS.items()}, counts)
        verify_records(second_package, result)

    def test_reexported_v2_retains_original_keys_after_target_rekeying(self):
        result = apply_records(self.source, plan_records(self.source, self.mappings), self.actor)
        self.record_receipt(result)
        reexport = export_records("application")
        self.assertEqual(reexport["format"], 2)
        incoming_key = str(self.source_graph["delivery"].pk)
        target_key = str(result["identity_map"]["deliveries"][incoming_key])
        origin = result["origins"]["deliveries"][incoming_key]
        self.assertEqual(reexport["provenance"]["identities"]["deliveries"][target_key], origin)
        index = load_identity_index()
        self.assertEqual(index[("deliveries", origin["namespace"], origin["key"])], int(target_key))
        context = reexport["provenance"]["publications"][str(self.source_graph["submission"].pk)]
        self.assertEqual(context["delivery_id"], self.source_graph["delivery"].pk)
        self.assertEqual(context["product_release_id"], self.source_graph["release"].pk)

    def test_reconciliation_detects_preexisting_row_changes(self):
        result = apply_records(self.source, plan_records(self.source, self.mappings), self.actor)
        Product.objects.filter(pk=self.target_graph["product"].pk).update(name="Changed after import")
        with self.assertRaisesMessage(TransferError, "Pre-existing products"):
            verify_records(self.source, result)

    def test_new_account_uses_fresh_target_key_and_stays_inactive(self):
        self.clear_business()
        owner_source_key = str(self.owner.pk)
        self.owner.delete()
        occupying = get_user_model().objects.create_user("unrelated-local-account", email="local@example.test", password="password")
        mappings = {str(self.actor.pk): self.actor.pk}
        plan = plan_records(self.source, mappings)
        self.assertFalse(plan["blockers"], plan["blockers"])
        result = apply_records(self.source, plan, self.actor)
        new_owner = get_user_model().objects.get(pk=result["user_mappings"][owner_source_key])
        self.assertNotEqual(new_owner.pk, occupying.pk)
        self.assertFalse(new_owner.is_active)
        self.assertFalse(new_owner.has_usable_password())
        self.assertFalse(new_owner.is_staff)
        self.assertFalse(new_owner.is_superuser)
        imported_job = Job.objects.get(pk=self.source_graph["job"].pk)
        self.assertEqual(imported_job.delivery.user_id, new_owner.pk)
        self.assertEqual(imported_job.requested_by_id, new_owner.pk)
        verify_records(self.source, result)

