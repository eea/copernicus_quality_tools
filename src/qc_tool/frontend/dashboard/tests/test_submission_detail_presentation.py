"""Receipt presentation uses loaded state and preserves every retained file."""

from types import SimpleNamespace

from django.test import SimpleTestCase

from qc_tool.frontend.dashboard.services.submissions.detail_presentation import (
    submission_detail_presentation,
)


class SubmissionDetailPresentationTests(SimpleTestCase):
    def submission(self, *, publication="published", review="pending", active=True,
                   coverage="authoritative", current=True, filename="delivery.v2.zip"):
        return SimpleNamespace(
            publication_state=publication,
            review_state=review,
            delivery=SimpleNamespace(filename=filename),
            product_release=SimpleNamespace(
                product=SimpleNamespace(is_active=active),
                coverage_state=coverage,
                is_current=current,
            ),
        )

    def presentation(self, submission=None, **kwargs):
        return submission_detail_presentation(
            submission or self.submission(),
            can_review=kwargs.pop("can_review", True),
            storage_available=kwargs.pop("storage_available", True),
            files=kwargs.pop("files", []),
            **kwargs,
        )

    def file(self, name):
        return {"name": name, "size": 123, "url": "/retained/{}".format(name)}

    def test_publication_does_not_mean_manager_approval(self):
        detail = self.presentation()
        self.assertEqual(detail["status"]["label"], "Awaiting review")
        self.assertEqual(detail["status"]["value"], "pending")
        self.assertEqual(detail["decision"], {
            "can_decide": True,
            "can_approve": True,
            "can_reject": True,
            "can_replace": False,
            "approval_block_reason": "",
        })

    def test_approved_incumbent_stays_approved_when_another_candidate_arrives(self):
        detail = self.presentation(
            self.submission(review="accepted"), conflict=SimpleNamespace(state="open"),
        )
        self.assertEqual(detail["status"]["label"], "Approved")
        self.assertEqual(detail["status"]["tone"], "success")
        self.assertIn("current delivery plan", detail["status"]["message"])
        for action in ("can_decide", "can_approve", "can_reject", "can_replace"):
            self.assertFalse(detail["decision"][action])

    def test_historical_approval_does_not_claim_current_product_completion(self):
        detail = self.presentation(self.submission(review="accepted", current=False))
        self.assertEqual(detail["status"]["label"], "Approved")
        self.assertIn("earlier delivery plan", detail["status"]["message"])
        self.assertNotIn("current delivery plan", detail["status"]["message"])

    def test_prepublication_state_takes_precedence_over_review_state(self):
        for publication, label, tone in (
            ("pending", "Preparing submission", "primary"),
            ("publishing", "Storing submission", "primary"),
            ("failed", "Submission failed", "danger"),
        ):
            with self.subTest(publication=publication):
                detail = self.presentation(self.submission(publication=publication, review="accepted"))
                self.assertEqual(detail["status"]["label"], label)
                self.assertEqual(detail["status"]["tone"], tone)
                self.assertEqual(detail["status"]["value"], publication)
                for action in ("can_decide", "can_approve", "can_reject", "can_replace"):
                    self.assertFalse(detail["decision"][action])

    def test_nonreviewer_has_no_decision_actions_or_configuration_guidance(self):
        detail = self.presentation(self.submission(active=False), can_review=False)
        for action in ("can_decide", "can_approve", "can_reject", "can_replace"):
            self.assertFalse(detail["decision"][action])
        self.assertEqual(detail["decision"]["approval_block_reason"], "")

    def test_stopped_product_or_unapproved_plan_still_allows_rejection(self):
        for active, coverage, reason in (
            (False, "authoritative", "product is stopped"),
            (True, "draft", "delivery plan must be approved"),
            (True, "unknown", "delivery plan must be approved"),
            (True, "retired", "delivery plan must be approved"),
        ):
            for conflict in (None, SimpleNamespace(state="open")):
                with self.subTest(active=active, coverage=coverage, conflict=conflict):
                    detail = self.presentation(
                        self.submission(active=active, coverage=coverage), conflict=conflict,
                    )
                    self.assertTrue(detail["decision"]["can_decide"])
                    self.assertTrue(detail["decision"]["can_reject"])
                    self.assertFalse(detail["decision"]["can_approve"])
                    self.assertFalse(detail["decision"]["can_replace"])
                    self.assertIn(reason, detail["decision"]["approval_block_reason"])

    def test_storage_outage_does_not_introduce_an_approval_restriction(self):
        available = self.presentation(storage_available=True)
        unavailable = self.presentation(storage_available=False)
        self.assertEqual(available["decision"], unavailable["decision"])
        self.assertEqual(unavailable["status"]["label"], "Awaiting review")

    def test_current_revision_is_not_an_additional_backend_approval_requirement(self):
        detail = self.presentation(self.submission(current=False))
        self.assertTrue(detail["decision"]["can_approve"])
        self.assertEqual(detail["decision"]["approval_block_reason"], "")

    def test_only_open_conflicts_offer_replacement(self):
        for state in ("open", "resolved", "dismissed"):
            with self.subTest(state=state):
                detail = self.presentation(
                    self.submission(review="conflict"), conflict=SimpleNamespace(state=state),
                )
                self.assertEqual(detail["decision"]["can_replace"], state == "open")
                self.assertEqual(detail["decision"]["can_approve"], state != "open")
                self.assertTrue(detail["decision"]["can_reject"])

    def test_rejected_receipt_retains_feedback_status_without_decision_controls(self):
        detail = self.presentation(self.submission(review="rejected"))
        self.assertEqual(detail["status"]["label"], "Rejected")
        self.assertIn("feedback", detail["status"]["message"])
        self.assertFalse(detail["decision"]["can_decide"])

    def test_exact_delivery_and_top_level_report_are_primary_and_every_file_remains(self):
        files = [self.file(name) for name in (
            "SUBMITTED", "delivery.v2_report.pdf", "input.d/delivery.v2.zip",
            "input.d/another.zip", "output.d/report.pdf", "report.pdf", "result.json",
        )]
        originals = [item.copy() for item in files]
        detail = self.presentation(files=iter(files))
        evidence = detail["evidence"]
        self.assertEqual(evidence["primary_files"], [
            {**files[2], "label": "submitted ZIP", "icon": "package"},
            {**files[1], "label": "QC report", "icon": "file"},
        ])
        self.assertEqual(evidence["supporting_files"], [files[index] for index in (0, 3, 4, 5, 6)])
        self.assertEqual(files, originals)
        self.assertIs(evidence["supporting_files"][0], files[0])
        self.assertEqual(len(evidence["primary_files"]) + len(evidence["supporting_files"]), len(files))

    def test_legacy_top_level_report_is_fallback_and_unknown_outputs_are_not_promoted(self):
        report = self.file("report.pdf")
        unrelated = self.file("output.d/custom_report.pdf")
        wrong_input = self.file("input.d/another.zip")
        evidence = self.presentation(files=[unrelated, report, wrong_input])["evidence"]
        self.assertEqual(evidence["primary_files"], [{**report, "label": "QC report", "icon": "file"}])
        self.assertEqual(evidence["supporting_files"], [unrelated, wrong_input])
        evidence = self.presentation(files=[unrelated, wrong_input])["evidence"]
        self.assertEqual(evidence["primary_files"], [])
        self.assertEqual(evidence["supporting_files"], [unrelated, wrong_input])

    def test_unavailable_storage_does_not_discard_supplied_inventory_entries(self):
        retained = self.file("input.d/delivery.v2.zip")
        detail = self.presentation(storage_available=False, files=[retained])
        self.assertEqual(detail["evidence"]["primary_files"][0]["url"], retained["url"])
