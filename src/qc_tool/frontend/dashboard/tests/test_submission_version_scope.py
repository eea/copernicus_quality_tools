"""Review queues and explicit approvals remain scoped to one catalog revision."""

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from qc_tool.frontend.dashboard.models import (
    DeliverySubmission, ProductRelease, ProductReleaseDefinition, ProductUnit,
)
from qc_tool.frontend.dashboard.services.catalog import get_product_coverage
from qc_tool.frontend.dashboard.tests.test_submission_workspace import SubmissionWorkspaceFixtureMixin


@override_settings(SUBMISSION_ENABLED=True)
class SubmissionVersionScopeTests(SubmissionWorkspaceFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.original = self.published()
        self.review(self.original, self.manager)
        self.previous = self.release
        self.previous.is_current = False
        self.previous.save(update_fields=("is_current",))
        self.release = ProductRelease.objects.create(
            product=self.product, release_key=self.previous.release_key, revision=2,
            description="Updated coverage", catalog_digest="e" * 64,
            coverage_state="authoritative", is_current=True, supersedes=self.previous,
            approved_at=timezone.now(),
        )
        ProductReleaseDefinition.objects.create(
            product_release=self.release, qc_definition=self.definition, is_primary=True,
        )
        ProductUnit.objects.create(
            product_release=self.release, product_unit_code="ee001l",
            source_value="EE001L1", provenance="manifest",
        )
        owner, delivery, _job, root = self.create_candidate("current-revision-owner")
        self.current = DeliverySubmission.objects.get(pk=self.submit(owner, delivery, root).submission_uuid)
        self.client.force_login(self.manager)

    def queue(self, **query):
        return self.client.get(reverse("submission_queue"), {
            "state": "all", "product": self.product.ident, **query,
        })

    def test_latest_revision_never_inherits_an_earlier_approval(self):
        self.assertEqual(get_product_coverage(self.previous).accepted, 1)
        self.assertEqual(get_product_coverage(self.release).accepted, 0)
        response = self.queue(state="accepted", release=self.release.pk)
        self.assertEqual(list(response.context["review_items"]), [])
        response = self.queue(state="accepted", release=self.previous.pk)
        self.assertEqual([item.pk for item in response.context["review_items"]], [self.original.pk])
        self.assertContains(response, "Historical revision for this series")
        self.assertContains(response, self.definition.digest[:12])
        details = self.client.get(self.review_url(self.original))
        self.assertContains(details, "No approval is implied for another revision.")

    def test_exact_revision_filter_limits_listing_and_bulk_confirmation(self):
        response = self.queue(release=self.release.pk)
        item, = response.context["review_items"]
        self.assertEqual(item.pk, self.current.pk)
        self.assertContains(response, 'name="release" value="{}"'.format(self.release.pk))
        action = response.context["bulk_action_url"]
        self.assertIn("release={}".format(self.release.pk), action)
        preview = self.client.post(action, {"selection": [item.bulk_selection], "intent": "preview"})
        self.assertEqual(preview.status_code, 200)
        self.assertIn("release={}".format(self.release.pk), preview.context["submission_workspace_url"])
        self.assertIn("revision 2", preview.content.decode())
        wrong_scope = action.replace("release={}".format(self.release.pk), "release={}".format(self.previous.pk))
        refused = self.client.post(wrong_scope, {"selection": [item.bulk_selection], "intent": "approve"})
        self.assertEqual(refused.status_code, 403)
        self.current.refresh_from_db()
        self.assertEqual(self.current.review_state, "pending")

    def test_invalid_and_unassigned_revision_filters_do_not_broaden_scope(self):
        for value in ("0", "-1", "not-an-id", "1/2", "9999999999999999999"):
            with self.subTest(value=value):
                self.assertEqual(list(self.queue(release=value).context["review_items"]), [])
        self.client.force_login(self.unassigned)
        self.assertEqual(list(self.queue(release=self.release.pk).context["review_items"]), [])
