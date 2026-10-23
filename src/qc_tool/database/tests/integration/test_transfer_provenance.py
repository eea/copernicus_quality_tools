"""Stable identities and original publication context on disposable databases."""

from copy import deepcopy
from uuid import NAMESPACE_URL, uuid4, uuid5
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from qc_tool.database.models import TransferReceipt
from qc_tool.database.transfers.contracts import TransferError, json_value
from qc_tool.database.transfers.provenance import (
    PUBLICATION_FIELDS, ensure_namespace, export_provenance,
    get_package_publication_identity, load_identity_index,
    publication_identity, validate_provenance,
)
from qc_tool.database.transfers.records import export_records, snapshot_current_application, validate_records
from qc_tool.frontend.dashboard.models import (
    Delivery, DeliverySubmission, Job, Product, ProductRelease,
    ProductReleaseDefinition, ProductUnit, QcDefinition,
)


class TransferProvenanceTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser("origin-admin", "admin@example.test", "password")
        self.product = Product.objects.create(ident="origin-product", name="Origin product")

    def receipt(self, mappings, origins, publications=None):
        targets = {}
        for key in publications or {}:
            submission = DeliverySubmission.objects.get(pk=key)
            targets[key] = {name: json_value(getattr(submission, name)) for name in PUBLICATION_FIELDS}
        return TransferReceipt.objects.create(
            package_id=uuid4(), package_sha256="a" * 64, operation_id=uuid4(),
            plan_sha256="b" * 64, profile="application", actor=self.actor,
            actor_name=self.actor.username,
            summary={"version": 1, "mode": "additive", "identity_map": mappings,
                     "origins": origins, "publication_identities": publications or {},
                     "publication_targets": targets},
        )

    def publication(self):
        definition = QcDefinition.objects.create(product_ident=self.product.ident, digest="a" * 64,
            description="Original definition", document={}, source_path="original.json")
        release = ProductRelease.objects.create(product=self.product, release_key="origin-stream", revision=1,
            description="Original release", catalog_digest="b" * 64, coverage_state="authoritative",
            approved_at=timezone.now(), approved_by=self.actor, is_current=True)
        ProductReleaseDefinition.objects.create(product_release=release, qc_definition=definition, is_primary=True)
        unit = ProductUnit.objects.create(product_release=release, product_unit_code="CZ", provenance="fixture")
        delivery = Delivery.objects.create(user=self.actor, filename="origin.zip", size_bytes=2,
            date_submitted=timezone.now(), content_sha256="c" * 64)
        job = Job.objects.create(delivery=delivery, product_ident=self.product.ident, product_description="Original",
            job_status="ok", product_release=release, qc_definition=definition, input_sha256="c" * 64)
        return DeliverySubmission.objects.create(delivery=delivery, job=job, product_release=release,
            product_unit=unit, product_unit_code=unit.product_unit_code,
            verified_product_unit_code=unit.product_unit_code,
            submitted_by=self.actor, submitted_by_username=self.actor.username, request_channel="browser",
            publication_state="published", published_at=timezone.now(), artifact_key="published/origin",
            artifact_digest="d" * 64, input_digest="c" * 64)

    def test_first_preview_is_read_only_and_legacy_compatible(self):
        with CaptureQueriesContext(connection) as queries:
            payload = export_records("application")
        self.assertEqual(payload["format"], 1)
        self.assertNotIn("provenance", payload)
        self.assertFalse(TransferReceipt.objects.exists())
        self.assertFalse(any(query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for query in queries))

    def test_namespace_is_persisted_once_and_export_has_complete_v2_identities(self):
        namespace = ensure_namespace()
        self.assertEqual(ensure_namespace(), namespace)
        self.assertEqual(TransferReceipt.objects.filter(profile="origin").count(), 1)
        origin = TransferReceipt.objects.get(profile="origin")
        self.assertEqual(str(origin.package_id), namespace)
        self.assertIsNone(origin.actor)
        payload = export_records("application")
        self.assertEqual(payload["format"], 2)
        provenance = payload["provenance"]
        self.assertEqual(provenance["namespace"], namespace)
        self.assertEqual(provenance["identities"]["products"][str(self.product.pk)],
                         {"namespace": namespace, "key": str(self.product.pk)})
        self.assertEqual(provenance["identities"]["accounts"][str(self.actor.pk)]["key"], str(self.actor.pk))
        self.assertEqual(validate_records(payload), payload)
        self.assertEqual(export_records("accounts")["format"], 1)

    def test_existing_additive_ledger_exports_v2_without_preview_writes(self):
        namespace = str(uuid4())
        receipt = self.receipt({"products": {"83": self.product.pk}},
                               {"products": {"83": {"namespace": namespace, "key": "17"}}})
        before = TransferReceipt.objects.count()
        payload = export_records("application")
        pending = str(uuid5(NAMESPACE_URL, "qc-tool-database-origin:" + str(receipt.operation_id)))
        self.assertEqual(payload["format"], 2)
        self.assertEqual(payload["provenance"]["namespace"], pending)
        self.assertEqual(payload["provenance"]["identities"]["products"][str(self.product.pk)],
                         {"namespace": namespace, "key": "17"})
        self.assertEqual(TransferReceipt.objects.count(), before)
        self.assertEqual(ensure_namespace(), pending)
        self.assertEqual(export_records("application")["provenance"], payload["provenance"])

    def test_multiple_aliases_can_reuse_one_target_and_first_alias_stays_canonical(self):
        first, second = str(uuid4()), str(uuid4())
        self.receipt({"products": {"3": self.product.pk}},
                     {"products": {"3": {"namespace": first, "key": "3"}}})
        self.receipt({"products": {"8": self.product.pk}},
                     {"products": {"8": {"namespace": second, "key": "8"}}})
        index = load_identity_index()
        self.assertEqual(index[("products", first, "3")], self.product.pk)
        self.assertEqual(index[("products", second, "8")], self.product.pk)
        self.assertEqual(export_records("application")["provenance"]["identities"]["products"][str(self.product.pk)],
                         {"namespace": first, "key": "3"})

    def test_local_alias_survives_import_while_exports_keep_original_origin(self):
        namespace = ensure_namespace()
        self.assertEqual(load_identity_index()[("products", namespace, str(self.product.pk))], self.product.pk)
        imported = str(uuid4())
        self.receipt({"products": {"88": self.product.pk}},
                     {"products": {"88": {"namespace": imported, "key": "88"}}})
        index = load_identity_index()
        self.assertEqual(index[("products", imported, "88")], self.product.pk)
        self.assertEqual(index[("products", namespace, str(self.product.pk))], self.product.pk)
        exported = export_records("application")["provenance"]["identities"]["products"][str(self.product.pk)]
        self.assertEqual(exported, {"namespace": imported, "key": "88"})

    def test_contradictory_mapping_for_one_origin_fails_closed(self):
        other = Product.objects.create(ident="other-origin", name="Other")
        namespace = str(uuid4())
        for target in (self.product.pk, other.pk):
            self.receipt({"products": {"5": target}}, {"products": {"5": {"namespace": namespace, "key": "5"}}})
        with self.assertRaisesMessage(TransferError, "contradictory destination"):
            load_identity_index()

    def test_local_alias_cannot_overwrite_a_contradictory_committed_mapping(self):
        namespace = ensure_namespace()
        other = Product.objects.create(ident="other-local-origin", name="Other")
        key = str(self.product.pk)
        self.receipt({"products": {key: other.pk}},
                     {"products": {key: {"namespace": namespace, "key": key}}})
        with self.assertRaisesMessage(TransferError, "local source identity conflicts"):
            load_identity_index()

    def test_malformed_and_future_ledger_evidence_is_refused(self):
        receipt = self.receipt({"products": {"5": self.product.pk}},
                               {"products": {"5": {"namespace": str(uuid4()), "key": "5"}}})
        original = deepcopy(receipt.summary)
        mutations = (
            lambda value: value.update(version=2),
            lambda value: value["identity_map"].update(arbitrary_table={"5": 1}),
            lambda value: value["identity_map"]["products"].update({"5": -1}),
            lambda value: value["origins"]["products"]["5"].update(key="../unsafe"),
            lambda value: value["origins"]["products"]["5"].update(namespace="not-a-uuid"),
            lambda value: value["origins"]["products"].clear(),
        )
        for mutation in mutations:
            summary = deepcopy(original)
            mutation(summary)
            TransferReceipt.objects.filter(pk=receipt.pk).update(summary=summary)
            with self.subTest(summary=summary), self.assertRaises(TransferError):
                load_identity_index()

    def test_multiple_database_origins_are_refused(self):
        ensure_namespace()
        namespace = str(uuid4())
        TransferReceipt.objects.create(package_id=namespace, package_sha256="a" * 64, operation_id=uuid4(),
            plan_sha256="b" * 64, profile="origin", actor_name="",
            summary={"version": 1, "namespace": namespace})
        with self.assertRaisesMessage(TransferError, "conflicting origin"):
            export_records("application")

    def test_ledger_scans_are_bounded_without_truncating(self):
        self.receipt({}, {})
        with patch("qc_tool.database.transfers.provenance.MAX_LEDGER_RECEIPTS", 0):
            with self.assertRaisesMessage(TransferError, "receipt bound"):
                load_identity_index()
        ensure_namespace()
        with patch("qc_tool.database.transfers.provenance.MAX_IDENTITY_BINDINGS", 0):
            with self.assertRaisesMessage(TransferError, "identity bound"):
                load_identity_index()

    def test_v2_inventory_unknown_fields_and_alias_collisions_are_refused(self):
        ensure_namespace()
        payload = export_records("application")
        mutations = (
            lambda value: value["provenance"].update(version=2),
            lambda value: value["provenance"].update(arbitrary_path="/tmp/unsafe"),
            lambda value: value["provenance"]["identities"].pop("products"),
            lambda value: value["provenance"]["identities"]["products"].update({"999": {"namespace": str(uuid4()), "key": "999"}}),
        )
        for mutation in mutations:
            changed = deepcopy(payload)
            mutation(changed)
            with self.subTest(changed=changed), self.assertRaises(TransferError):
                validate_records(changed)
        other = Product.objects.create(ident="duplicate-origin", name="Other")
        payload = export_records("application")
        payload["provenance"]["identities"]["products"][str(other.pk)] = deepcopy(
            payload["provenance"]["identities"]["products"][str(self.product.pk)])
        with self.assertRaisesMessage(TransferError, "duplicate source"):
            validate_records(payload)

    def test_original_publication_integer_ids_survive_local_rekeying(self):
        submission = self.publication()
        row = next(row for row in export_records("application")["records"]["submissions"] if row["submission_uuid"] == str(submission.pk))
        original = {name: row[name] for name in PUBLICATION_FIELDS}
        original.update(delivery_id=71, product_release_id=82, product_unit_id=93)
        namespace = str(uuid4())
        key = str(submission.pk)
        self.receipt({"submissions": {key: key}},
                     {"submissions": {key: {"namespace": namespace, "key": key}}}, {key: original})
        payload = export_records("application")
        self.assertEqual(payload["provenance"]["publications"][key], original)
        self.assertEqual(publication_identity(submission), original)
        self.assertEqual(get_package_publication_identity(payload, row), original)
        self.assertEqual(validate_provenance(payload)["publications"][key]["delivery_id"], 71)
        self.assertEqual(DeliverySubmission.objects.get(pk=submission.pk).delivery_id, submission.delivery_id)

    def test_legacy_publication_context_is_complete_and_read_only(self):
        submission = self.publication()
        payload = export_records("application")
        row = payload["records"]["submissions"][0]
        self.assertEqual(get_package_publication_identity(payload, row), {name: row[name] for name in PUBLICATION_FIELDS})
        self.assertIsNone(publication_identity(submission))
        self.assertFalse(TransferReceipt.objects.exists())

    def test_original_overlay_is_bound_to_the_approved_local_parent_identities(self):
        submission = self.publication()
        row = export_records("application")["records"]["submissions"][0]
        original = {name: row[name] for name in PUBLICATION_FIELDS}
        original.update(delivery_id=71, product_release_id=82, product_unit_id=93)
        key, namespace = str(submission.pk), str(uuid4())
        self.receipt({"submissions": {key: key}},
                     {"submissions": {key: {"namespace": namespace, "key": key}}}, {key: original})
        self.assertEqual(publication_identity(submission), original)
        submission.delivery_id += 100
        with self.assertRaisesMessage(TransferError, "approved destination"):
            publication_identity(submission)
        # A coherent direct SQL edit of both parent edges must not make an old
        # manifest valid for a different destination association on re-export.
        other = Delivery.objects.create(user=self.actor, filename="unrelated.zip", size_bytes=2,
            date_submitted=timezone.now(), content_sha256="c" * 64)
        with connection.cursor() as cursor:
            cursor.execute("UPDATE publication_submission SET delivery_id=%s WHERE submission_uuid=%s",
                           [other.pk, submission._meta.pk.get_db_prep_value(submission.pk, connection)])
        Job.objects.filter(pk=submission.job_id).update(delivery_id=other.pk)
        with self.assertRaisesMessage(TransferError, "approved destination"):
            export_records("application")

    def test_publication_receipt_without_approved_target_context_fails_closed(self):
        submission = self.publication()
        row = export_records("application")["records"]["submissions"][0]
        context = {name: row[name] for name in PUBLICATION_FIELDS}
        key, namespace = str(submission.pk), str(uuid4())
        receipt = self.receipt({"submissions": {key: key}},
            {"submissions": {key: {"namespace": namespace, "key": key}}}, {key: context})
        summary = dict(receipt.summary)
        summary.pop("publication_targets")
        TransferReceipt.objects.filter(pk=receipt.pk).update(summary=summary)
        with self.assertRaisesMessage(TransferError, "publication provenance"):
            publication_identity(submission)

    def test_artifact_identity_reads_only_matching_receipts_and_specific_json_leaves(self):
        submission = self.publication()
        row = export_records("application")["records"]["submissions"][0]
        original = {name: row[name] for name in PUBLICATION_FIELDS}
        original.update(delivery_id=71, product_release_id=82, product_unit_id=93)
        key, namespace = str(submission.pk), str(uuid4())
        self.receipt({"submissions": {key: key}},
                     {"submissions": {key: {"namespace": namespace, "key": key}}}, {key: original})
        unrelated = self.receipt({}, {})
        TransferReceipt.objects.filter(pk=unrelated.pk).update(summary={
            "version": 999, "mode": "additive", "identity_map": {"unreviewed_resource": {}},
            "publication_identities": {str(uuid4()): {"unrelated": "unreadable"}},
        })
        with patch("qc_tool.database.transfers.provenance._receipt_state", side_effect=AssertionError("Full ledger read")):
            with CaptureQueriesContext(connection) as queries:
                self.assertEqual(publication_identity(submission), original)
        self.assertEqual(len(queries), 1)
        # Global export continues to reject malformed history; isolating an
        # artifact lookup does not turn corruption into valid export evidence.
        with self.assertRaisesMessage(TransferError, "Unsupported additive"):
            export_records("application")

    def test_point_lookup_bounds_matches_and_rejects_contradictory_context(self):
        submission = self.publication()
        row = export_records("application")["records"]["submissions"][0]
        original = {name: row[name] for name in PUBLICATION_FIELDS}
        key, namespace = str(submission.pk), str(uuid4())
        self.receipt({"submissions": {key: key}},
                     {"submissions": {key: {"namespace": namespace, "key": key}}}, {key: original})
        with patch("qc_tool.database.transfers.provenance.MAX_PUBLICATION_RECEIPTS", 0):
            with self.assertRaisesMessage(TransferError, "provenance receipt bound"):
                publication_identity(submission)
        changed = dict(original, delivery_id=original["delivery_id"] + 71)
        self.receipt({"submissions": {key: key}},
                     {"submissions": {key: {"namespace": namespace, "key": key}}}, {key: changed})
        with self.assertRaisesMessage(TransferError, "contradictory original"):
            publication_identity(submission)

    def test_point_lookup_requires_a_matching_committed_submission_mapping(self):
        submission = self.publication()
        row = export_records("application")["records"]["submissions"][0]
        context = {name: row[name] for name in PUBLICATION_FIELDS}
        key, namespace = str(submission.pk), str(uuid4())
        receipt = self.receipt({"submissions": {key: key}},
            {"submissions": {key: {"namespace": namespace, "key": key}}}, {key: context})
        summary = dict(receipt.summary)
        summary["identity_map"] = {"submissions": {}}
        TransferReceipt.objects.filter(pk=receipt.pk).update(summary=summary)
        with self.assertRaisesMessage(TransferError, "committed record mapping"):
            publication_identity(submission)

    def test_source_overrides_reexport_as_full_audit_records_without_changing_target(self):
        original = deepcopy(export_records("application")["records"]["products"][0])
        original.update(id=83, name="Original incoming name")
        namespace = str(uuid4())
        receipt = self.receipt({"products": {"83": self.product.pk}},
                               {"products": {"83": {"namespace": namespace, "key": "17"}}})
        summary = dict(receipt.summary)
        summary["source_overrides"] = {"products": {"83": original}}
        TransferReceipt.objects.filter(pk=receipt.pk).update(summary=summary)
        payload = export_records("application")
        expected = {"resource": "products", "target_key": str(self.product.pk),
                    "origin": {"namespace": namespace, "key": "17"}, "record": original}
        self.assertEqual(payload["provenance"]["source_records"], [expected])
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Origin product")
        self.assertEqual(validate_records(payload), payload)
        # A subsequent transfer carries audit records as data. Repeated exact
        # evidence is de-duplicated, rather than lost or multiplied on export.
        later = self.receipt({"products": {"901": self.product.pk}},
                             {"products": {"901": {"namespace": namespace, "key": "17"}}})
        summary = dict(later.summary)
        summary["source_evidence"] = [expected]
        TransferReceipt.objects.filter(pk=later.pk).update(summary=summary)
        self.assertEqual(export_records("application")["provenance"]["source_records"], [expected])

    def test_source_evidence_rejects_unknown_fields_paths_and_unincluded_targets(self):
        ensure_namespace()
        payload = export_records("application")
        entry = {"resource": "products", "target_key": str(self.product.pk),
                 "origin": {"namespace": str(uuid4()), "key": "17"},
                 "record": deepcopy(payload["records"]["products"][0])}
        payload["provenance"]["source_records"] = [entry]
        self.assertEqual(validate_records(payload), payload)
        mutations = (
            lambda row: row.update(resource="arbitrary_table"),
            lambda row: row.update(target_key="../../unsafe"),
            lambda row: row.update(target_key="999999"),
            lambda row: row["record"].update(unreviewed_field="not allowed"),
            lambda row: row["record"].update(name=17),
            lambda row: row.update(path="/tmp/not-allowed"),
        )
        for mutation in mutations:
            changed = deepcopy(payload)
            mutation(changed["provenance"]["source_records"][0])
            with self.subTest(changed=changed), self.assertRaises(TransferError):
                validate_records(changed)
        changed = deepcopy(payload)
        changed["provenance"]["source_records"].append(deepcopy(entry))
        with self.assertRaisesMessage(TransferError, "duplicate"):
            validate_records(changed)
        with patch("qc_tool.database.transfers.provenance.record_limit", return_value=0):
            with self.assertRaisesMessage(TransferError, "bounded record list"):
                validate_provenance(payload)

    def source_evidence_receipt(self):
        original = deepcopy(export_records("application")["records"]["products"][0])
        namespace = str(uuid4())
        receipt = self.receipt({"products": {"83": self.product.pk}},
            {"products": {"83": {"namespace": namespace, "key": "17"}}})
        entries = [{"resource": "products", "target_key": str(self.product.pk),
                    "origin": {"namespace": namespace, "key": "17"},
                    "record": {**original, "name": "Original revision " + str(revision)}}
                   for revision in (1, 2)]
        summary = {**receipt.summary, "source_evidence": entries}
        TransferReceipt.objects.filter(pk=receipt.pk).update(summary=summary)
        return entries

    def test_persisted_source_evidence_remains_readable_below_current_upload_limit(self):
        entries = self.source_evidence_receipt()
        payload = export_records("application")
        with override_settings(QC_TOOL_TRANSFER_MAX_RECORDS=1), CaptureQueriesContext(connection) as queries:
            self.assertEqual(export_provenance(payload)["source_records"], entries)
            self.assertEqual(validate_provenance(payload, enforce_package_limits=False), payload["provenance"])
            with self.assertRaisesMessage(TransferError, "bounded record list"):
                validate_provenance(payload)
        self.assertFalse(any(query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for query in queries))

    def test_internal_snapshot_propagates_trusted_provenance_bounds_without_dropping_evidence(self):
        entries = self.source_evidence_receipt()
        with override_settings(QC_TOOL_TRANSFER_MAX_RECORDS=1):
            snapshot = snapshot_current_application()
            self.assertEqual(snapshot["provenance"]["source_records"], entries)
            with self.assertRaisesMessage(TransferError, "record limit"):
                validate_records(snapshot)
            invalid = deepcopy(snapshot)
            invalid["provenance"]["source_records"][0]["record"]["name"] = 42
            with self.assertRaisesMessage(TransferError, "invalid value type"):
                validate_records(invalid, enforce_package_limits=False)

    def test_trusted_provenance_and_persisted_evidence_still_obey_ledger_bound(self):
        self.source_evidence_receipt()
        payload = export_records("application")
        with patch("qc_tool.database.transfers.provenance.MAX_IDENTITY_BINDINGS", 1):
            with self.assertRaisesMessage(TransferError, "bound"):
                export_provenance(payload)
            with self.assertRaisesMessage(TransferError, "bounded record list"):
                validate_provenance(payload, enforce_package_limits=False)

    def test_publication_overlay_cannot_change_uuid_input_codes_time_or_select_paths(self):
        self.publication()
        ensure_namespace()
        payload = export_records("application")
        key = payload["records"]["submissions"][0]["submission_uuid"]
        for field, value in (("job_id", str(uuid4())), ("submission_uuid", str(uuid4())),
                             ("input_digest", "e" * 64), ("product_unit_code", "UA"),
                             ("requested_at", json_value(timezone.now())), ("path", "/tmp/unsafe"),
                             ("delivery_id", -1)):
            changed = deepcopy(payload)
            changed["provenance"]["publications"][key][field] = value
            with self.subTest(field=field), self.assertRaises(TransferError):
                validate_records(changed)

