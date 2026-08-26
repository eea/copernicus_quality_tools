"""Scoped product-manager access to the conflict review admin."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import DeliverySubmission
from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.dashboard.models import Product
from qc_tool.frontend.dashboard.models import ProductAOI
from qc_tool.frontend.dashboard.models import ProductRelease
from qc_tool.frontend.dashboard.models import ProductReleaseDefinition
from qc_tool.frontend.dashboard.models import QcDefinition


class SubmissionAdminScopeTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.manager = user_model.objects.create_user(
            username="scoped-product-manager",
            password="password",
        )
        self.manager.groups.add(
            Group.objects.get(name=Role.PRODUCT_MANAGER.value)
        )
        self.manager.refresh_from_db()
        UserProductGrant.objects.create(
            user=self.manager,
            product_ident="managed-definition",
        )
        self.visible = self.create_submission(
            product_ident="managed-definition",
            suffix="visible",
        )
        self.hidden = self.create_submission(
            product_ident="other-definition",
            suffix="hidden",
        )
        self.client.force_login(self.manager)

    def create_submission(self, *, product_ident, suffix):
        definition = QcDefinition.objects.create(
            product_ident=product_ident,
            digest=("a" if suffix == "visible" else "b") * 64,
            description=suffix,
            document={"description": suffix, "steps": []},
            source_path="{}.json".format(product_ident),
        )
        product = Product.objects.create(
            ident=product_ident,
            name=suffix,
        )
        release = ProductRelease.objects.create(
            product=product,
            release_key="{}-release".format(suffix),
            revision=1,
            description=suffix,
            catalog_digest=("c" if suffix == "visible" else "d") * 64,
            coverage_state=ProductRelease.CoverageState.AUTHORITATIVE,
            is_current=True,
            approved_at=timezone.now(),
        )
        ProductReleaseDefinition.objects.create(
            product_release=release,
            qc_definition=definition,
            is_primary=True,
        )
        product_aoi = ProductAOI.objects.create(
            product_release=release,
            aoi_code="{}-aoi".format(suffix),
            provenance="manifest",
        )
        owner = get_user_model().objects.create_user(
            username="{}-owner".format(suffix)
        )
        delivery = Delivery.objects.create(
            user=owner,
            filename="{}.zip".format(suffix),
            size_bytes=1,
            aoi_code_submitted=product_aoi.aoi_code,
            date_submitted=timezone.now(),
        )
        job = Job.objects.create(
            delivery=delivery,
            job_status="ok",
            product_ident=product_ident,
            product_description=suffix,
            aoi_code=product_aoi.aoi_code,
            aoi_code_submitted=product_aoi.aoi_code,
            product_release=release,
            qc_definition=definition,
            input_sha256=("1" if suffix == "visible" else "2") * 64,
        )
        return DeliverySubmission.objects.create(
            delivery=delivery,
            job=job,
            product_release=release,
            product_aoi=product_aoi,
            aoi_code=product_aoi.aoi_code,
            aoi_code_submitted=product_aoi.aoi_code,
            submitted_by=owner,
            submitted_by_username=owner.username,
            request_channel=DeliverySubmission.RequestChannel.BROWSER,
            publication_state=DeliverySubmission.PublicationState.PUBLISHED,
            published_at=delivery.date_submitted,
            artifact_path="/published/{}".format(suffix),
            artifact_digest=("e" if suffix == "visible" else "f") * 64,
            input_digest=job.input_sha256,
        )

    def test_product_manager_is_staff_but_sees_only_granted_candidates(self):
        self.assertTrue(self.manager.is_staff)

        response = self.client.get(
            reverse("admin:dashboard_deliverysubmission_changelist")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, str(self.visible.submission_uuid))
        self.assertNotContains(response, str(self.hidden.submission_uuid))

    def test_product_manager_does_not_gain_unrelated_account_admin_access(self):
        response = self.client.get(reverse("admin:auth_user_changelist"))

        self.assertEqual(response.status_code, 403)
