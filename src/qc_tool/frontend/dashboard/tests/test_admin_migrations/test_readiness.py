"""Migration administration readiness behavior."""

from copy import deepcopy

from django.urls import reverse

from .fixtures import MigrationAdminTestCase


class MigrationReadinessTests(MigrationAdminTestCase):
    def test_get_is_read_only_and_shows_backup_risks_and_installed_history(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        for text in ("Database migrations", "3.0.0", "dashboard.0001_initial",
                     "One historical report is missing.", reverse("admin_backup_export")):
            self.assertContains(response, text)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("private", response["Cache-Control"])
        self.assertEqual(response["Pragma"], "no-cache")
        self.assertIn("Cookie", response["Vary"])
        self.assertTemplateUsed(response, "dashboard/shared/header.html")
        self.assertNotContains(response, "qc-admin-navigation")
        self.preview.assert_not_called()
        self.start.assert_not_called()
        self.activate.assert_not_called()


    def test_overview_explains_prerequisites_and_current_stage(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Ready — workers paused")
        self.assertContains(response, "Initialize Django migration history")
        self.assertContains(response, "History-free v3.0.0")
        self.assertContains(response, "The installed QC Tool version remains v3.0.0")
        self.assertContains(response, "Review history initialization")
        self.assertContains(response, "Pause and back up")
        self.assertContains(response, 'aria-current="step"')
        self.assertContains(response, "Refresh overview")


    def test_ready_schema_does_not_offer_an_unneeded_upgrade(self):
        self.overview["database"].update(state="ready", pending=[])
        self.overview.update(can_prepare=False)
        response = self.client.get(self.url)
        self.assertContains(response, "No database upgrade is needed")
        self.assertNotContains(response, 'value="review"')
        self.assertNotContains(response, 'id="migration-backup-heading"')
        self.assertContains(response, "View applied migrations")
        self.assertContains(response, "Creating a new migration")
        self.preview.assert_not_called()


    def test_future_pending_release_keeps_the_upgrade_journey(self):
        self.overview.update(installed_release="3.0.1", source_release="managed history")
        self.overview["database"].update(state="pending")
        self.review.update(source_release="managed history", target_release="3.0.1")
        response = self.client.get(self.url)
        self.assertContains(response, "Review a backup")
        self.assertContains(response, "Review upgrade")
        self.assertContains(response, "Pending Django migrations")
        self.assertNotContains(response, "The installed QC Tool version remains v3.0.0")
        self.assertNotContains(response, "Review history initialization")
        response = self.client.post(self.url, {"action": "review", "backup_id": self.backup_id})
        self.assertContains(response, "Review this upgrade")
        self.assertContains(response, "Prepare upgraded copy")
        self.assertNotContains(response, "Initialize history on a copy")
        self.start.assert_not_called()


    def test_maintenance_off_disables_copy_review_and_explains_next_action(self):
        self.overview["maintenance"]["phase"] = "off"
        self.overview.update(can_prepare=False, preparation_blockers=["Enable maintenance before review."])
        response = self.client.get(self.url)
        self.assertContains(response, "Turn on maintenance")
        self.assertContains(response, "Enable maintenance before review.")
        self.assertContains(response, 'value="review" disabled')


    def test_drift_is_reported_once_and_never_offers_repair(self):
        self.overview["database"].update(state="incompatible", problems=["Unexpected delivery column."])
        self.overview.update(can_prepare=False, blockers=["Unexpected delivery column."],
                             preparation_blockers=["Unexpected delivery column."])
        response = self.client.get(self.url)
        self.assertContains(response, "Unexpected delivery column.", count=1)
        self.assertContains(response, "Investigate the database before upgrading")
        self.assertNotContains(response, 'value="review"')
        self.assertContains(response, "Review intervention guidance")
        self.assertContains(response, "Inspect databases")


    def test_unsupported_backend_does_not_guide_an_unavailable_copy_workflow(self):
        self.overview.update(can_prepare=False, preparation_blockers=["Administrator native upgrades require PostgreSQL."])
        response = self.client.get(self.url)
        self.assertContains(response, "Resolve the initialization prerequisites")
        self.assertContains(response, "Administrator native upgrades require PostgreSQL.")
        self.assertContains(response, 'value="review" disabled')


    def test_backup_eligibility_and_blockers_are_visible(self):
        changed = deepcopy(self.overview)
        changed["backups"][0].update(eligible=False, blockers=["This backup belongs to another database."])
        self.status.return_value = changed
        response = self.client.get(self.url)
        self.assertContains(response, "This backup belongs to another database.")
        self.assertContains(response, 'value="review" disabled')
