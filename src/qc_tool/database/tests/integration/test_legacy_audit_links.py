"""Historical audit rows must never link to unrelated target objects."""

from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Group
from django.db import connection
from django.test import TestCase

from qc_tool.database.legacy.importer import apply_import, prepare_import
from qc_tool.database.tests.integration.test_legacy_import import synthetic_legacy_dump


class LegacyAuditLinkTests(TestCase):
    def _import_log(self, *, app_label, model, object_id):
        dump = synthetic_legacy_dump("!synthetic-unusable-password")
        dump.tables["django_content_type"] = [{"id": "8", "app_label": app_label, "model": model}]
        dump.tables["django_admin_log"] = [{
            "id": "12", "action_time": "2024-06-01 12:00:00+00",
            "object_id": object_id, "object_repr": "Historical object",
            "action_flag": "2", "change_message": "Historical change",
            "content_type_id": "8", "user_id": "47",
        }]
        apply_import(prepare_import(dump), target_database=str(connection.settings_dict["NAME"]))
        return LogEntry.objects.get(pk=12)

    def test_legacy_group_log_cannot_point_at_new_canonical_group(self):
        canonical_id = str(Group.objects.get(name="default").pk)
        entry = self._import_log(app_label="auth", model="group", object_id=canonical_id)
        self.assertIsNone(entry.content_type_id)
        self.assertEqual(entry.object_id, canonical_id)
        self.assertEqual(entry.object_repr, "Historical object")
        self.assertEqual(entry.change_message, "Historical change")
        self.assertEqual(entry.user_id, 47)

    def test_deleted_user_log_has_no_link_to_a_future_reused_id(self):
        entry = self._import_log(app_label="auth", model="user", object_id="999")
        self.assertIsNone(entry.content_type_id)
        self.assertEqual(entry.object_id, "999")

    def test_retained_user_preserves_its_audit_link(self):
        entry = self._import_log(app_label="auth", model="user", object_id="47")
        self.assertEqual(entry.content_type.natural_key(), ("auth", "user"))
        self.assertEqual(entry.object_id, "47")

    def test_retained_delivery_preserves_its_audit_link(self):
        entry = self._import_log(app_label="dashboard", model="delivery", object_id="901")
        self.assertEqual(entry.content_type.natural_key(), ("dashboard", "delivery"))

    def test_retained_job_preserves_its_audit_link(self):
        entry = self._import_log(app_label="dashboard", model="job", object_id="00000000-0000-0000-0000-0000000003e9")
        self.assertEqual(entry.content_type.natural_key(), ("dashboard", "job"))

    def test_retained_storage_source_preserves_its_audit_link(self):
        entry = self._import_log(app_label="dashboard", model="s3info", object_id="701")
        self.assertEqual(entry.content_type.natural_key(), ("dashboard", "s3info"))
