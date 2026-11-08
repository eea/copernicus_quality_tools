"""Migration administration reviews behavior."""

from qc_tool.database.transfers.errors import TransferError

from .fixtures import MigrationAdminTestCase


class MigrationReviewTests(MigrationAdminTestCase):
    def test_review_is_explicit_and_does_not_enqueue(self):
        response = self.client.post(self.url, {"action": "review", "backup_id": self.backup_id})
        self.assertContains(response, "Review Django history initialization")
        self.assertContains(response, "Remote S3 objects require separate recovery.")
        self.assertContains(response, "Review history initialization, then prepare a copy")
        self.assertContains(response, "Initialize history on a copy")
        self.preview.assert_called_once_with(self.backup_id, actor=self.administrator)
        self.start.assert_not_called()


    def test_review_distinguishes_storage_inventory_from_candidate_verification(self):
        self.review.update(storage_areas=[{"key": "deliveries", "label": "Delivery archives", "status": "included",
                                          "files_count": 3, "byte_count": 2048},
                                         {"key": "artifacts", "label": "QC artifacts", "status": "unavailable",
                                          "files_count": 0, "byte_count": 0}],
                           storage_exclusions=["Private runtime journals require separate recovery."])
        response = self.client.post(self.url, {"action": "review", "backup_id": self.backup_id})
        for text in ("Delivery archives", "QC artifacts", "Unavailable", "candidate compatibility is verified after migration",
                     "Worker input and temporary directories", "Private runtime journals require separate recovery."):
            self.assertContains(response, text)
        self.start.assert_not_called()


    def test_start_requires_confirmation_and_keeps_submitted_review(self):
        values = {"action": "start", "backup_id": self.backup_id, "review_hash": "d" * 64,
                  "generation": 4, "revision": 0}
        response = self.client.post(self.url, values)
        self.assertEqual(response.status_code, 400)
        self.start.assert_not_called()
        self.assertContains(response, 'value="' + "d" * 64 + '"', status_code=400)
        values["confirmed_backup"] = "on"
        response = self.client.post(self.url, values)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response["Location"], self.url + "?operation=" + self.operation_id)
        self.start.assert_called_once_with(self.backup_id, actor=self.administrator,
                                          review_hash="d" * 64, generation=4, revision=0)


    def test_stale_review_error_is_visible_without_start_retry(self):
        self.start.side_effect = TransferError("The source changed. Review this backup again.")
        response = self.client.post(self.url, {"action": "start", "backup_id": self.backup_id,
            "review_hash": "d" * 64, "generation": 4, "revision": 0, "confirmed_backup": "on"})
        self.assertContains(response, "The source changed.", status_code=409)
        self.assertEqual(self.start.call_count, 1)
