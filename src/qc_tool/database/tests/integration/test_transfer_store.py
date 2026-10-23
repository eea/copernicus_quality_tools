"""Fail-closed parsing and durable private transfer journal boundaries."""

import copy
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase, override_settings

from qc_tool.database.transfers import store
from qc_tool.database.transfers.errors import TransferError


class TransferJournalTests(SimpleTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        override = override_settings(QC_TOOL_TRANSFER_DIR=str(Path(temporary.name) / "transfers"))
        override.enable()
        self.addCleanup(override.disable)
        self.operation_id = str(uuid4())
        self.path = store.operation_dir(self.operation_id, create=True) / "operation.json"
        self.operation = {"version": 1, "id": self.operation_id, "kind": "import", "status": "staged",
                          "actor_id": 1, "actor_name": "operator", "created_at": store.now(),
                          "updated_at": store.now(), "message": "", "error": "", "result": {}, "plan": None}

    def write_raw(self, payload):
        self.path.write_bytes(payload)
        self.path.chmod(0o600)

    def test_rejects_duplicate_and_nonfinite_json(self):
        for payload in (b'{"status":"completed","status":"running"}', b'{"value":NaN}',
                        b'{"value":Infinity}'):
            with self.subTest(payload=payload[:60]):
                self.write_raw(payload)
                with self.assertRaisesMessage(TransferError, "journal cannot be read safely"):
                    store.read_json(self.path)

    def test_rejects_malformed_operation_shapes_without_raw_exceptions(self):
        for value in ([], None, "invalid", {**self.operation, "version": True},
                      {**self.operation, "kind": []}, {**self.operation, "status": []},
                      {**self.operation, "result": []}, {**self.operation, "created_at": "not-a-date"},
                      {**self.operation, "created_at": "2026-10-21T12:00:00"}):
            with self.subTest(value=value):
                self.write_raw(json.dumps(value).encode())
                with self.assertRaises(TransferError):
                    store.read_operation(self.operation_id)

    def test_oversized_write_keeps_previous_readable_journal(self):
        store.write_json(self.path, self.operation)
        original = self.path.read_bytes()
        oversized = copy.deepcopy(self.operation)
        oversized["message"] = "x" * 1000
        with patch.object(store, "MAX_JOURNAL_BYTES", len(original)):
            with self.assertRaisesMessage(TransferError, "private journal limit"):
                store.write_json(self.path, oversized)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(store.read_operation(self.operation_id), self.operation)

    def test_unsupported_write_keeps_previous_readable_journal(self):
        store.write_json(self.path, self.operation)
        for value in (float("nan"), {1, 2}):
            with self.assertRaisesMessage(TransferError, "unsupported data"):
                store.write_json(self.path, {**self.operation, "result": value})
        self.assertEqual(store.read_operation(self.operation_id), self.operation)

    def test_unsafe_execution_lock_refuses_with_controlled_error(self):
        lock = store.directory() / "execution.lock"
        lock.symlink_to(self.path)
        with self.assertRaisesMessage(TransferError, "locking is unavailable"):
            with store.execution_lock():
                self.fail("An unsafe lock must never admit an operation.")

