"""Migration administration history behavior."""


from .fixtures import MigrationAdminTestCase


class MigrationHistoryTests(MigrationAdminTestCase):
    def test_pending_plan_explains_changes_and_non_atomic_risks_with_escaped_descriptions(self):
        self.overview["database"].update(state="pending", pending=[{
            "app": "dashboard", "name": "0002_example", "atomic": False,
            "operations": ["Add delivery field", "<script>unsafe()</script>"]}])
        response = self.client.get(self.url)
        self.assertContains(response, "Update available")
        self.assertContains(response, "dashboard.0002_example")
        self.assertContains(response, "Add delivery field")
        self.assertContains(response, "Non-atomic migration")
        self.assertContains(response, "&lt;script&gt;unsafe()&lt;/script&gt;")
        self.assertNotContains(response, "<script>unsafe()</script>")
        self.start.assert_not_called()


    def test_applied_recorder_history_is_distinct_from_operation_history(self):
        self.overview["database"].update(state="ready", pending=[],
            applied=[{"app": "dashboard", "name": "0001_initial"}],
            applied_history=[{"app": "dashboard", "name": "0001_initial",
                              "applied_at": "2026-11-06T12:00:00+00:00"}])
        response = self.client.get(self.url)
        self.assertContains(response, "Applied Django migrations (1)")
        self.assertContains(response, "Recorded at")
        self.assertContains(response, "2026")
        self.assertContains(response, "QC Tool data")
        self.assertContains(response, "No upgrade copies have been prepared")
        self.assertContains(response, "initialization time")
        self.start.assert_not_called()


    def test_same_release_forward_operation_is_not_labelled_as_history_initialization(self):
        self.overview.update(active_database="qc_tool_upgrade")
        self.overview["database"].update(state="ready", pending=[])
        self.overview["maintenance"]["phase"] = "off"
        self.get_operation.return_value = {**self.operation, "status": "completed", "runner_active": False,
            "maintenance_owned": False, "upgrade": {"source_release": "3.0.0", "target_release": "3.0.0",
                                                       "initializes_history": False}}
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(response, "Upgrade complete; QC Tool is open")
        self.assertNotContains(response, "History initialization complete")


    def test_migration_authoring_is_guidance_without_a_runtime_mutation(self):
        response = self.client.get(self.url)
        self.assertContains(response, "A developer creates migration files")
        self.assertContains(response, "matching frontend and worker images")
        response = self.client.post(self.url, {"action": "makemigrations"})
        self.assertEqual(response.status_code, 400)
        self.start.assert_not_called()
        self.recover.assert_not_called()
        self.activate.assert_not_called()


    def test_active_copy_does_not_repeat_the_journals_old_switch_instruction(self):
        self.overview.update(active_database="qc_tool_upgrade")
        self.overview["database"].update(state="ready", pending=[])
        self.overview["maintenance"]["phase"] = "off"
        item = {**self.operation, "status": "completed", "runner_active": False,
                "maintenance_owned": False, "message": "Review and approve the database switch separately."}
        self.overview["operations"] = [item]
        self.get_operation.return_value = item
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(response, "This copy is the active database")
        self.assertNotContains(response, "Review and approve the database switch separately.")


    def test_stopped_upgrade_and_history_use_actionable_statuses(self):
        stopped = {**self.operation, "status": "failed", "runner_active": False, "maintenance_owned": False,
                   "can_retry": False, "can_abandon": False}
        self.get_operation.return_value = stopped
        self.overview["operations"] = [stopped]
        response = self.client.get(self.url, {"operation": self.operation_id})
        self.assertContains(response, "History initialization stopped; copy retained")
        self.assertContains(response, "Stopped; copy retained")
        self.assertNotContains(response, 'value="retry"')
