"""Explicit schema compatibility without SQL repair or implicit data conversion."""

from copy import deepcopy
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext

from qc_tool.database.transfers.compatibility import (
    compare_descriptors, inspect_compatibility, model_contract, producer_metadata,
    postgres_model_columns, require_compatibility, schema_descriptor, target_schema_status,
)
from qc_tool.database.transfers.contracts import TransferError, canonical_bytes
from qc_tool.database.transfers.provenance import ensure_namespace
from qc_tool.database.transfers.records import (
    apply_records, export_records, plan_records, validate_records,
)


def archive(records, metadata=None):
    return SimpleNamespace(records=records, manifest={"profile": records["profile"]},
                           storage={} if metadata is None else {"compatibility": metadata})


def native_inventory(tables):
    return {"profile": "database", "inventory": {"tables": tables},
            "source_details": {"app_version": "3.0.0-source"}}


def native_tables_from_models():
    return [{"schema": schema, "name": name, "columns": list(columns.values())}
            for (schema, name), columns in postgres_model_columns().items()]


class CompatibilityDescriptorTests(SimpleTestCase):
    def test_installed_descriptor_is_semantic_and_deterministic_without_database_access(self):
        with patch("qc_tool.database.transfers.contracts.inspect.getsource", side_effect=AssertionError("source inspection")):
            first = schema_descriptor()
            self.assertEqual(canonical_bytes(first), canonical_bytes(schema_descriptor()))
            self.assertEqual(compare_descriptors(first, first), [])
        self.assertEqual(first["source_validation"]["revision"], 1)
        self.assertIn("jobs", first["resources"])
        self.assertTrue(all("source_sha256" not in row for row in first["models"]))

    def test_every_application_resource_declares_all_reviewed_stored_fields(self):
        from qc_tool.database.transfers.records import RESOURCE_FIELDS
        descriptor = schema_descriptor()
        for name, (model, fields) in RESOURCE_FIELDS.items():
            self.assertEqual(descriptor["resources"][name],
                             {"model": model._meta.label_lower, "fields": list(fields)})

    def test_comparison_explains_added_removed_type_nullability_relationship_and_constraints(self):
        source = schema_descriptor()
        target = deepcopy(source)
        model = next(row for row in target["models"] if row["model"] == "dashboard.delivery")
        size = next(row for row in model["fields"] if row["name"] == "size_bytes")
        size.update(type="TextField", null=True)
        owner = next(row for row in model["fields"] if row["name"] == "user_id")
        owner["relation"]["on_delete"] = "django.db.models.deletion.PROTECT"
        removed = next(row for row in model["fields"] if row["name"] == "filename")
        model["fields"].remove(removed)
        model["fields"].append({**deepcopy(size), "name": "future_field"})
        model["constraints"].append({"declaration": ["future", [], {}]})
        changes = compare_descriptors(source, target)
        kinds = {item["kind"] for item in changes}
        self.assertTrue({"field_added", "field_removed", "type_changed", "nullability_changed",
                         "relationship_changed", "constraints_changed"} <= kinds)
        self.assertTrue(any(item["path"].endswith("." + removed["name"]) for item in changes))

    def test_validation_policy_change_is_not_silently_accepted_as_equivalent_schema(self):
        first = schema_descriptor()
        second = deepcopy(first)
        second["source_validation"]["revision"] += 1
        self.assertNotEqual(model_contract("accounts", first), model_contract("accounts", second))
        self.assertEqual(compare_descriptors(first, second)[0]["kind"], "validation_changed")

    def test_choice_label_changes_are_presentation_but_allowed_values_are_semantic(self):
        from qc_tool.frontend.dashboard.models import DeliverySubmission
        field = DeliverySubmission._meta.get_field("review_state")
        descriptor = schema_descriptor()
        relabeled = [(value, "Updated label " + str(index))
                     for index, (value, _label) in enumerate(field.flatchoices)]
        with patch.object(field, "_choices", relabeled):
            self.assertEqual(schema_descriptor(), descriptor)
        with patch.object(field, "_choices", [*relabeled, ("future-state", "Future")]):
            self.assertNotEqual(schema_descriptor(), descriptor)

    def test_duplicate_field_or_unknown_descriptor_version_is_rejected(self):
        for mode in ("duplicate", "version"):
            descriptor = schema_descriptor()
            if mode == "duplicate":
                descriptor["models"][0]["fields"].append(descriptor["models"][0]["fields"][0])
            else:
                descriptor["version"] += 1
            with self.subTest(mode=mode), self.assertRaises(TransferError):
                compare_descriptors(descriptor, schema_descriptor())

    def test_native_metadata_does_not_require_the_installed_orm_contract(self):
        with patch("qc_tool.database.transfers.compatibility.schema_descriptor", side_effect=AssertionError("ORM dependency")):
            metadata = producer_metadata("database")
            report = inspect_compatibility(archive({"profile": "database"}, metadata))
        self.assertIsNone(metadata["schema"])
        self.assertEqual(report["status"], "native")
        self.assertTrue(report["supported"])

    def test_native_schema_preview_uses_offline_postgresql_types_and_not_portable_reader(self):
        tables = native_tables_from_models()
        user = next(table for table in tables if table["name"] == "auth_user")
        username = next(column for column in user["columns"] if column["name"] == "username")
        self.assertEqual(username["type"], "varchar(150)")
        username["type"] = "character varying(150)"
        with patch("qc_tool.database.transfers.compatibility.schema_descriptor", side_effect=AssertionError("portable reader")), \
                patch("django.db.backends.postgresql.base.DatabaseWrapper.get_new_connection", side_effect=AssertionError("SQL connection")):
            report = inspect_compatibility(archive(native_inventory(tables)))
        self.assertEqual(report["status"], "native")
        self.assertEqual(report["changes"], [])
        self.assertTrue(report["supported"])
        self.assertIsNone(report["schema_ready"])
        self.assertTrue(report["activation_requires_check"])
        self.assertEqual(report["source_release"], "3.0.0-source")

    def test_native_schema_differences_are_informative_and_do_not_block_preservation(self):
        tables = native_tables_from_models()
        user = next(table for table in tables if table["name"] == "auth_user")
        next(column for column in user["columns"] if column["name"] == "username")["type"] = "text"
        next(column for column in user["columns"] if column["name"] == "email")["nullable"] = True
        user["columns"] = [column for column in user["columns"] if column["name"] != "first_name"]
        user["columns"].append({"name": "older_extra", "type": "integer", "nullable": False})
        tables[:] = [table for table in tables if table["name"] != "qc_database_transfer_receipt"]
        tables.append({"schema": "public", "name": "source_only_table", "columns": []})
        incoming = archive(native_inventory(tables))
        report = require_compatibility(incoming)
        self.assertTrue(report["supported"])
        self.assertFalse(report["schema_ready"])
        self.assertEqual(report["status"], "native-schema-drift")
        self.assertTrue({"model_added", "model_removed", "field_added", "field_removed",
                         "type_changed", "nullability_changed"} <= {item["kind"] for item in report["changes"]})
        self.assertIn("partial preview", report["message"])

    def test_native_preview_unavailable_or_malformed_does_not_claim_schema_readiness(self):
        for records in ({"profile": "database"}, native_inventory([{"schema": "public", "name": "bad", "columns": None}])):
            report = inspect_compatibility(archive(records, {"source_release": "producer-fallback"}))
            self.assertTrue(report["supported"])
            self.assertIsNone(report["schema_ready"])
            self.assertEqual(report["changes"], [])
            self.assertIn("preview is unavailable", report["message"])
        incoming = archive({"profile": "database"}, {"source_release": "producer-fallback"})
        self.assertEqual(inspect_compatibility(incoming)["source_release"], "producer-fallback")

    def test_target_inspection_reports_empty_drift_and_connectivity_without_apply(self):
        inspector_path = "qc_tool.database.transfers.compatibility.SchemaInitializer"
        reports = (
            {"state": "ready", "problems": [], "table_count": 24},
            {"state": "empty", "problems": [], "table_count": 0},
            {"state": "incompatible", "problems": ["missing table example"], "table_count": 23},
        )
        for expected in reports:
            with self.subTest(state=expected["state"]), patch(inspector_path) as initializer:
                initializer.return_value.inspect.return_value = expected
                report = target_schema_status()
                self.assertEqual(report["ready"], expected["state"] == "ready")
                self.assertEqual(report["problems"], expected["problems"])
                initializer.return_value.apply.assert_not_called()
        with patch(inspector_path) as initializer, self.assertLogs("qc_tool.database.transfers.compatibility", level="ERROR"):
            initializer.return_value.inspect.side_effect = DatabaseError("connection failed")
            self.assertEqual(target_schema_status()["state"], "unavailable")
            initializer.return_value.apply.assert_not_called()


class PortableCompatibilityTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser("compat-admin", "compat@example.test", "password")

    def package(self, profile="accounts"):
        return archive(export_records(profile, semantic_contract=True), producer_metadata(profile))

    def test_semantic_accounts_round_trip_retains_inactive_user_authority_boundary(self):
        with patch("qc_tool.database.transfers.contracts.inspect.getsource", side_effect=AssertionError("source-only dependency")):
            incoming = self.package()
            self.assertEqual(incoming.records["format"], 3)
            self.assertEqual(require_compatibility(incoming)["status"], "compatible")
        incoming.records["accounts"][0]["username"] = "compat-imported"
        result = apply_records(incoming.records, plan_records(incoming.records), actor=self.actor)
        imported = get_user_model().objects.get(username="compat-imported")
        self.assertFalse(imported.is_active)
        self.assertFalse(imported.is_superuser)
        self.assertFalse(imported.has_usable_password())
        self.assertEqual(result["created_counts"]["accounts"], 1)

    def test_semantic_application_preserves_optional_provenance_without_preview_writes(self):
        with CaptureQueriesContext(connection) as queries:
            incoming = self.package("application")
            self.assertTrue(require_compatibility(incoming)["supported"])
        self.assertNotIn("provenance", incoming.records)
        self.assertFalse(any(row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for row in queries))
        namespace = ensure_namespace()
        incoming = self.package("application")
        self.assertEqual(incoming.records["provenance"]["namespace"], namespace)
        self.assertEqual(validate_records(incoming.records), incoming.records)

    def test_source_declared_drift_is_structured_and_blocked_without_data_changes(self):
        incoming = self.package()
        descriptor = incoming.storage["compatibility"]["schema"]
        model = next(row for row in descriptor["models"] if row["model"] == "auth.user")
        next(row for row in model["fields"] if row["name"] == "email")["max_length"] = 500
        contract = model_contract("accounts", descriptor)
        incoming.records["contract"] = incoming.storage["compatibility"]["model_contract"] = contract
        with CaptureQueriesContext(connection) as queries:
            report = inspect_compatibility(incoming)
            self.assertFalse(report["supported"])
            self.assertEqual(report["status"], "schema-drift")
            self.assertTrue(any(item["path"] == "auth.user.email.max_length" for item in report["changes"]))
            with self.assertRaisesMessage(TransferError, "semantic model contract differs"):
                validate_records(incoming.records)
        self.assertEqual(list(queries), [])

    def test_missing_tampered_or_unknown_metadata_never_grants_compatibility(self):
        for mode in ("missing", "digest", "version", "profile", "contract_version", "payload_version"):
            incoming = self.package()
            if mode == "missing":
                incoming.storage.clear()
            elif mode == "digest":
                incoming.storage["compatibility"]["model_contract"] = "a" * 64
            elif mode == "profile":
                incoming.storage["compatibility"]["profile"] = "application"
            elif mode == "payload_version":
                incoming.records["contract_version"] = True
            else:
                incoming.storage["compatibility"][mode] = 99
            with self.subTest(mode=mode):
                self.assertFalse(inspect_compatibility(incoming)["supported"])
                with self.assertRaises(TransferError):
                    require_compatibility(incoming)

    def test_legacy_formats_remain_strict_without_inferring_a_reader_from_release(self):
        for profile in ("accounts", "application"):
            incoming = archive(export_records(profile))
            self.assertTrue(require_compatibility(incoming)["supported"])
            incoming.records["contract"] = "a" * 64
            report = inspect_compatibility(incoming)
            self.assertEqual(report["status"], "legacy-unsupported")
            self.assertFalse(report["supported"])
            with self.assertRaisesMessage(TransferError, "package model contract differs"):
                validate_records(incoming.records)

    def test_semantic_format_requires_exact_fields_and_supported_integer_version(self):
        for mode in ("unknown", "bool", "missing", "extra"):
            incoming = self.package().records
            if mode == "unknown":
                incoming["contract_version"] = 99
            elif mode == "bool":
                incoming["contract_version"] = True
            elif mode == "missing":
                incoming.pop("contract_version")
            else:
                incoming["future_field"] = "must not be dropped"
            with self.subTest(mode=mode), self.assertRaises(TransferError):
                validate_records(incoming)


@skipUnless(connection.vendor == "postgresql", "PostgreSQL catalog types require a disposable PostgreSQL test database")
class NativeSchemaPreviewPostgresTests(TestCase):
    def test_real_model_created_postgresql_catalog_matches_the_offline_preview_without_more_sql(self):
        # This fixture query runs only in Django's disposable test database. The
        # compatibility comparison itself must not query either live/source SQL.
        with connection.cursor() as cursor:
            cursor.execute("""SELECT n.nspname, c.relname, a.attname,
                format_type(a.atttypid, a.atttypmod), NOT a.attnotnull
                FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                JOIN pg_attribute a ON a.attrelid=c.oid
                WHERE n.nspname='public' AND c.relkind IN ('r','p')
                AND a.attnum>0 AND NOT a.attisdropped
                ORDER BY c.relname,a.attnum""")
            tables = {}
            for schema, table, name, datatype, nullable in cursor.fetchall():
                tables.setdefault((schema, table), []).append({"name": name, "type": datatype, "nullable": nullable})
        fixture = native_inventory([{"schema": schema, "name": name, "columns": columns}
                                    for (schema, name), columns in tables.items()])
        with CaptureQueriesContext(connection) as queries:
            report = inspect_compatibility(archive(fixture))
        self.assertEqual(list(queries), [])
        self.assertEqual(report["status"], "native")
        self.assertEqual(report["changes"], [])
        self.assertTrue(report["supported"])
        self.assertIsNone(report["schema_ready"])
