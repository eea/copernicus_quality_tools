"""Export execution belongs to the server; requests only observe retained bytes."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, RequestFactory, SimpleTestCase, TransactionTestCase, override_settings
from django.urls import reverse

from qc_tool.database.transfers import postgres, service, store
from qc_tool.database.transfers.archive import inspect_archive
from qc_tool.frontend.dashboard.services import maintenance
from qc_tool.frontend.dashboard.services.maintenance.operations import active_operation
from qc_tool.frontend.dashboard.views.admin_data_transfer import data_transfer_status


class DetachedTransferLaunchTests(SimpleTestCase):
    def test_launch_detaches_from_request_input_and_does_not_wait_for_completion(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(override_settings(QC_TOOL_TRANSFER_DIR=directory / "transfers"))
        operation = {"id": str(uuid4())}
        private = store.operation_dir(operation["id"], create=True)

        with patch.object(service.subprocess, "Popen") as launch:
            service._launch(operation)

        launch.assert_called_once()
        arguments, = launch.call_args.args
        self.assertEqual(arguments, [sys.executable, "-m", "qc_tool.frontend.manage",
                                     "data_transfer", "run", operation["id"]])
        options = launch.call_args.kwargs
        self.assertTrue(options["start_new_session"])
        self.assertTrue(options["close_fds"])
        self.assertEqual(options["stdin"], subprocess.DEVNULL)
        self.assertIs(options["stdout"], options["stderr"])
        self.assertEqual(Path(options["stdout"].name), private / "runner.log")
        self.assertTrue(options["stdout"].closed)
        launch.return_value.wait.assert_not_called()
        launch.return_value.communicate.assert_not_called()
        self.assertEqual((private / "runner.log").stat().st_mode & 0o777, 0o600)


@override_settings(QC_TOOL_TRANSFER_MIN_FREE_BYTES=1024**2)
class TransferRequestLifecycleTests(TransactionTestCase):
    """A completed ZIP is independent of the creating response and browser."""

    def setUp(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(override_settings(
            QC_TOOL_MAINTENANCE_DIR=directory / "maintenance",
            QC_TOOL_TRANSFER_DIR=directory / "transfers", MAINTENANCE_MODE=False,
        ))
        self.actor = get_user_model().objects.create_superuser(
            "background-operator", "background@example.test", "test-password")
        self.client.force_login(self.actor)
        self.generation = maintenance.enable(self.actor, 0)["generation"]
        maintenance.advance(self.generation)
        self.launch = self.enterContext(patch.object(service, "_launch"))
        self.metadata = {
            "format": "qc-tool-postgresql", "version": 1,
            "created_at": "2026-10-23T12:00:00+00:00", "review_hash": "a" * 64,
            "counts": {"tables": 24, "rows": 5},
        }
        self.enterContext(patch.object(postgres, "preview", return_value=self.metadata))
        self.capture = self.enterContext(patch.object(postgres, "capture_stream", side_effect=self.dump))
        self.enterContext(patch.object(service, "database_availability", return_value={
            "ready": True, "message": "", "can_create_restore_database": False,
        }))
        self.url = reverse("admin_data_transfer")

    def dump(self, output, **_options):
        data = b"PGDMP synthetic server-created backup"
        output.write(data)
        return {**self.metadata, "dump_sha256": hashlib.sha256(data).hexdigest(), "dump_bytes": len(data)}

    def create_from_request(self):
        selection = {"profile": "database", "user_ids": [], "components": []}
        preview = service.export_preview(selection, self.actor)
        response = self.client.post(self.url, {
            "action": "export", "scope": "database", "components": [],
            "reviewed_hash": preview["review_hash"], "generation": self.generation,
        })
        self.assertEqual(response.status_code, 303)
        operation, = service.list_operations(self.actor)
        self.assertEqual(response["Location"], self.url + "?operation=" + operation["id"] + "#transfer-operation")
        response.close()
        return operation

    def test_reload_and_return_requests_observe_one_queued_operation_without_driving_it(self):
        operation = self.create_from_request()
        self.assertEqual(operation["status"], "queued")
        original_journal = (store.operation_dir(operation["id"]) / "operation.json").read_bytes()

        with patch.object(service, "run_operation") as run, \
                patch.object(service, "recover_operation") as recover:
            for _reload in range(2):
                response = self.client.get(self.url, {"operation": operation["id"]})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Creating your export")
                response.close()
                status = self.client.get(reverse("admin_data_transfer_status", args=[operation["id"]]))
                self.assertEqual(status.json()["status"], "queued")
            self.assertEqual(self.client.get(self.url, {"tab": "history"}).status_code, 200)
            run.assert_not_called()
            recover.assert_not_called()

        self.launch.assert_called_once()
        self.capture.assert_not_called()
        self.assertEqual((store.operation_dir(operation["id"]) / "operation.json").read_bytes(), original_journal)
        self.assertEqual(active_operation()["operation_id"], operation["id"])

    def test_finished_package_survives_abandoned_download_and_new_browser_requests(self):
        operation = self.create_from_request()
        # The original request is gone before the dedicated runner does its work.
        self.client = Client()
        service.run_operation(operation["id"])
        package = store.operation_dir(operation["id"]) / "package.zip"
        checksum = hashlib.sha256(package.read_bytes()).hexdigest()
        download_url = reverse("admin_data_transfer_download", args=[operation["id"]])

        for attempt in range(3):
            browser = Client()
            browser.force_login(self.actor)
            history = browser.get(self.url, {"tab": "history"})
            self.assertContains(history, download_url)
            history.close()
            response = browser.get(download_url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "application/zip")
            self.assertIn("attachment;", response["Content-Disposition"])
            if attempt == 0:
                next(iter(response.streaming_content))
                response.close()  # Closing a connection does not release its export.
            else:
                data = b"".join(response.streaming_content)
                response.close()
                self.assertEqual(hashlib.sha256(data).hexdigest(), checksum)
            self.assertTrue(package.is_file())
            self.assertEqual(service.get_operation(operation["id"], self.actor)["status"], "completed")

        self.capture.assert_called_once()
        self.launch.assert_called_once()
        self.assertEqual(len(service.list_operations(self.actor)), 1)
        self.assertIsNone(active_operation())


@skipUnless(connection.vendor == "postgresql", "A real native runner requires disposable PostgreSQL")
@override_settings(QC_TOOL_TRANSFER_MIN_FREE_BYTES=1024**2)
class NativeBackgroundProcessTests(TransactionTestCase):
    def test_real_detached_runner_finishes_without_a_live_creation_request(self):
        name = str(connection.settings_dict["NAME"])
        self.assertTrue(name.startswith("test_"), "Refusing a native runner outside a disposable test database")
        directory = Path(self.enterContext(TemporaryDirectory()))
        work = directory / "work"
        self.enterContext(override_settings(
            QC_TOOL_MAINTENANCE_DIR=work / "maintenance",
            QC_TOOL_TRANSFER_DIR=work / "data-transfer", MAINTENANCE_MODE=False,
        ))
        actor = get_user_model().objects.create_superuser(
            "detached-native-operator", "native-background@example.test", "test-password")
        generation = maintenance.enable(actor, 0)["generation"]
        maintenance.advance(generation)
        availability = postgres.availability()
        self.assertTrue(availability["available"], availability["reason"])
        selection = {"profile": "database", "user_ids": [], "components": []}
        preview = service.export_preview(selection, actor)

        child_environment = {
            "DB_ENGINE": "postgres", "POSTGRES_DB": name,
            "WORK_DIR": str(work), "QC_TOOL_TRANSFER_DIR": str(work / "data-transfer"),
            "QC_TOOL_ENVIRONMENT": "test", "MAINTENANCE_MODE": "no",
            "QC_TOOL_TRANSFER_MIN_FREE_BYTES": str(1024**2),
        }
        for option, variable in (("HOST", "POSTGRES_HOST"), ("PORT", "POSTGRES_PORT"),
                                 ("USER", "POSTGRES_USER"), ("PASSWORD", "POSTGRES_PASSWORD")):
            child_environment[variable] = str(connection.settings_dict.get(option) or "")
        children = []
        original_popen = subprocess.Popen

        def spawn(*args, **kwargs):
            child = original_popen(*args, **kwargs)
            children.append(child)
            return child

        def stop_children():
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=10)

        self.addCleanup(stop_children)
        with patch.dict(os.environ, child_environment), patch.object(service.subprocess, "Popen", side_effect=spawn):
            operation = service.create_export(selection, actor, preview["review_hash"], generation)
        self.assertEqual(len(children), 1)
        child = children[0]
        factory = RequestFactory()
        statuses = []
        deadline = time.monotonic() + 45
        with patch.object(service, "run_operation") as inline_run, patch.object(service, "_launch") as relaunch:
            while True:
                request = factory.get(reverse("admin_data_transfer_status", args=[operation["id"]]))
                request.user = actor
                response = data_transfer_status(request, operation["id"])
                self.assertEqual(response.status_code, 200)
                statuses.append(json.loads(response.content)["status"])
                response.close()
                if child.poll() is not None:
                    break
                self.assertLess(time.monotonic(), deadline, "The isolated background export did not finish")
                try:
                    child.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    pass
            inline_run.assert_not_called()
            relaunch.assert_not_called()

        # Runner diagnostics may contain private backup metadata; keep them out
        # of assertion failures and the test output.
        self.assertEqual(child.returncode, 0, "The isolated background transfer runner failed")
        completed = service.get_operation(operation["id"], actor)
        self.assertEqual(completed["status"], "completed")
        self.assertTrue(completed["downloadable"])
        self.assertEqual(statuses[-1], "completed")
        self.assertIsNone(active_operation())
        retained = store.operation_dir(operation["id"]) / "package.zip"
        verified = inspect_archive(retained)
        self.assertEqual(verified.records["source"]["database"], name)
        self.assertGreaterEqual(verified.records["counts"]["rows"], 1)
        for _download in range(2):
            stream, _metadata = service.download_operation(operation["id"], actor)
            with stream:
                self.assertEqual(hashlib.file_digest(stream, "sha256").hexdigest(), verified.package_sha256)
