"""Database choices identify the live copy and keep switch authority explicit."""

from django.template.loader import render_to_string
from django.test import SimpleTestCase

from qc_tool.frontend.dashboard.forms.data_transfers import DatabaseActivationForm, DatabaseControlForm


class AdminDatabaseSwitchPresentationTests(SimpleTestCase):
    def test_database_controls_identify_the_live_copy_without_unrelated_backup_tasks(self):
        html = render_to_string("admin/includes/transfers/database_controls.html", {
            "database_control": {"active_database": "live_database"},
        })
        self.assertIn("QC Tool uses one database at a time.", html)
        self.assertIn("live_database", html)
        self.assertNotIn("Restore from backup", html)
        self.assertNotIn('value="rollback_database"', html)

    def test_switch_review_labels_both_copies_without_a_database_name_typing_step(self):
        form = DatabaseActivationForm(
            prefix="activation", destination="restored_database", requires_credentials=True,
            initial={"review_hash": "a" * 64, "revision": 4, "generation": 7},
        )
        html = render_to_string("admin/includes/transfers/operation.html", {
            "operation": {"id": "812d54c5-f69b-4f51-9e25-d4cbbd9a35da", "kind": "import", "status": "completed"},
            "activation_form": form,
            "rollback_form": DatabaseControlForm(prefix="rollback", destination="live_database"),
            "activation_review": {"source_database": "live_database", "target_database": "restored_database",
                                  "can_apply": True, "warnings": ["An external artifact needs separate recovery."]},
            "maintenance_ready": True,
        })
        for label in ("Currently in use", "Use after switching", "Keep for recovery", "Use this database"):
            self.assertIn(label, html)
        self.assertIn("An external artifact needs separate recovery.", html)
        self.assertIn("Quick recovery expires when maintenance is turned off.", html)
        for field in ("activation-destination_confirmation", "activation-confirmed_storage", "activation-username", "activation-password"):
            self.assertIn('name="' + field + '"', html)
        self.assertIn('<input type="hidden" name="activation-destination_confirmation" value="restored_database"', html)
        self.assertNotIn("Type the database name", html)
        self.assertIn('value="activate_database"', html)
        self.assertIn('data-transfer-pending-label="Checking and switching…"', html)
        self.assertIn("data-transfer-pending-status", html)

    def test_expired_quick_recovery_keeps_the_database_visible_and_button_disabled(self):
        html = render_to_string("admin/includes/transfers/database_controls.html", {
            "database_control": {"active_database": "live_database", "previous_database": "previous_database",
                                 "rollback_blockers": ["Maintenance already ended. Both databases remain retained."]},
            "rollback_form": DatabaseControlForm(prefix="rollback", destination="previous_database"),
            "maintenance_ready": True,
        })
        self.assertIn("Switch back to previous_database", html)
        self.assertIn("before you reopen QC Tool to changes", html)
        self.assertIn("Maintenance already ended.", html)
        self.assertIn("<fieldset disabled>", html)
        self.assertIn('<input type="hidden" name="rollback-destination_confirmation" value="previous_database"', html)
        self.assertNotIn("Type the database name", html)
