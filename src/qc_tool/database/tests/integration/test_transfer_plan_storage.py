"""Compact journals retain decisions; verified packages/SQL own full records."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from django.test import SimpleTestCase, TestCase, override_settings

from qc_tool.database.models import TransferReceipt
from qc_tool.database.transfers import store
from qc_tool.database.transfers.errors import TransferError
from qc_tool.database.transfers.plan_storage import (
    compact_operation, compact_plan, public_result, validate_stored_plan, verify_rebuilt_plan,
)


def core_plan():
    return {"mode": "additive", "version": 1, "profile": "application",
            "mappings": {}, "resolutions": {}, "included": {"units": ["1"]},
            "pending": {"units": [{"id": 1, "product_unit_code": "unit-1"}]},
            "origins": {"units": {"1": {"namespace": str(uuid4()), "key": "1"}}},
            "identity_map": {"units": {"1": 1}}, "actions": {"units": {"1": "create"}}}


class JournalFixtures:
    def setUp(self):
        super().setUp()
        self.directory = Path(self.enterContext(TemporaryDirectory(prefix="qc-plan-storage-")))
        self.enterContext(override_settings(QC_TOOL_TRANSFER_DIR=self.directory / "transfers"))
        identity = str(uuid4())
        store.operation_dir(identity, create=True)
        self.operation = {"version": 1, "id": identity, "kind": "import", "status": "planned",
            "actor_id": 1, "actor_name": "operator", "created_at": store.now(), "updated_at": store.now(),
            "message": "", "error": "", "result": {}, "plan": {"plan_hash": "a" * 64},
            "core_plan": core_plan()}


class PlanStorageTests(JournalFixtures, SimpleTestCase):
    def test_only_reproducible_copies_are_removed_and_verified_rebuild_is_exact(self):
        original = deepcopy(self.operation)
        compact = compact_operation(self.operation)
        self.assertEqual(self.operation, original)
        self.assertNotIn("pending", compact["core_plan"])
        for key in ("mode", "version", "mappings", "resolutions", "included"):
            self.assertEqual(compact["core_plan"][key], original["core_plan"][key])
        self.assertEqual(compact["plan"], original["plan"])
        self.assertIs(verify_rebuilt_plan(compact["core_plan"], self.operation["core_plan"]), self.operation["core_plan"])
        self.assertEqual(compact_plan(compact["core_plan"]), compact["core_plan"])

    def test_changed_rebuilt_source_or_decisions_cannot_reuse_a_review(self):
        compact = compact_plan(self.operation["core_plan"])
        for mode in ("source", "mapping", "included"):
            changed = deepcopy(self.operation["core_plan"])
            if mode == "source": changed["pending"]["units"][0]["product_unit_code"] = "changed"
            elif mode == "mapping": changed["mappings"]["source-user"] = 5
            else: changed["included"]["units"] = []
            with self.subTest(mode=mode), self.assertRaisesMessage(TransferError, "plan changed"):
                verify_rebuilt_plan(compact, changed)

    def test_invalid_compact_marker_or_retained_subset_fails_closed_on_read(self):
        compact = compact_plan(self.operation["core_plan"])
        for mode in ("version", "digest", "included", "extra"):
            changed = deepcopy(compact)
            if mode == "version": changed["_plan_storage"]["version"] = True
            elif mode == "digest": changed["_plan_storage"]["core_sha256"] = "not-a-digest"
            elif mode == "included": changed["included"]["units"] = ["another"]
            else: changed["pending"] = {}
            operation = {**self.operation, "core_plan": changed}
            store.write_json(store.operation_dir(operation["id"]) / "operation.json", operation)
            with self.subTest(mode=mode), self.assertRaisesMessage(TransferError, "plan reference is invalid"):
                store.read_operation(operation["id"])

    def test_existing_full_and_unknown_future_journals_are_not_blindly_compacted(self):
        core = self.operation["core_plan"]
        store.write_json(store.operation_dir(self.operation["id"]) / "operation.json", self.operation)
        self.assertEqual(store.read_operation(self.operation["id"])["core_plan"], core)
        self.assertIs(verify_rebuilt_plan(core, core), core)
        for changed in ({**core, "version": 2}, {**core, "mode": "future-reader"},
                        {**core, "unreviewed_private_field": "retain"}):
            self.assertIs(compact_plan(changed), changed)
        future_result = {"mode": "additive", "version": 2, "unknown_audit": "retain"}
        self.assertIs(public_result(future_result), future_result)

    def test_130238_record_review_fits_existing_journal_bound_without_pending_duplicates(self):
        count = 130_238
        core = self.operation["core_plan"]
        core["included"] = {"units": [str(index) for index in range(count)]}
        core["pending"] = {"units": [{"id": index, "original_metadata": "x" * 400} for index in range(count)]}
        full_bytes = json.dumps(self.operation, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
        self.assertGreater(len(full_bytes), store.MAX_JOURNAL_BYTES)
        store.save_operation(self.operation)
        persisted = store.read_operation(self.operation["id"])
        self.assertEqual(persisted["core_plan"]["included"], core["included"])
        self.assertEqual(len(core["pending"]["units"]), count)
        self.assertLess((store.operation_dir(self.operation["id"]) / "operation.json").stat().st_size, 2 * 1024**2)
        verify_rebuilt_plan(persisted["core_plan"], core)


class ReceiptSummaryStorageTests(JournalFixtures, TestCase):
    def test_private_summary_is_compact_while_sql_receipt_and_memory_remain_complete(self):
        result = {"mode": "additive", "version": 1, "created_counts": {"units": 1},
                  "identity_map": {"units": {"source": 1}}, "origins": {"units": {"source": "origin"}},
                  "expected": {"units": {"1": {"all_original_fields": "retained"}}},
                  "baseline": {"preexisting_rows": "all retained"}, "records_digest": "b" * 64,
                  "destination_jobs": [], "file_references": {"total": 0}}
        receipt = TransferReceipt.objects.create(package_id=uuid4(), package_sha256="c" * 64,
            operation_id=self.operation["id"], plan_sha256="a" * 64, profile="application",
            actor_name="operator", summary=result)
        self.operation.update(status="completed", result=result)
        store.save_operation(self.operation)
        stored = store.read_operation(self.operation["id"])
        self.assertEqual(stored["result"], public_result(result))
        self.assertNotIn("expected", stored["result"])
        receipt.refresh_from_db()
        self.assertEqual(receipt.summary, result)
        self.assertEqual(self.operation["result"], result)
