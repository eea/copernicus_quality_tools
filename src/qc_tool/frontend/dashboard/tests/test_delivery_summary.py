"""Tests for access-scoped delivery summary aggregation."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone

from qc_tool.common import JOB_ERROR
from qc_tool.common import JOB_FAILED
from qc_tool.common import JOB_OK
from qc_tool.common import JOB_RUNNING
from qc_tool.frontend.accounts.authorization import access_for
from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.dashboard.services.deliveries import summarize_deliveries


class DeliverySummaryTests(TestCase):
    """Count the latest QC state only within the effective delivery scope."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="delivery-summary-user",
            password="test-password",
        )
        UserProductGrant.objects.create(user=self.user, product_ident="test-product")

    def create_delivery(self, *, user, filename, is_deleted=False):
        return Delivery.objects.create(
            user=user,
            filename=filename,
            size_bytes=1024,
            is_deleted=is_deleted,
        )

    def create_job(self, *, delivery, status, created_at):
        return Job.objects.create(
            delivery=delivery,
            date_created=created_at,
            job_status=status,
            product_ident="test-product",
            product_description="Test product",
        )

    def test_uses_visible_deliveries_and_each_latest_job(self):
        now = timezone.now()
        passed = self.create_delivery(user=self.user, filename="passed.zip")
        self.create_job(
            delivery=passed,
            status=JOB_FAILED,
            created_at=now - timedelta(hours=2),
        )
        self.create_job(
            delivery=passed,
            status=JOB_OK,
            created_at=now - timedelta(hours=1),
        )

        in_progress = self.create_delivery(
            user=self.user,
            filename="in-progress.zip",
        )
        self.create_job(
            delivery=in_progress,
            status=JOB_RUNNING,
            created_at=now,
        )

        failed = self.create_delivery(user=self.user, filename="failed.zip")
        self.create_job(delivery=failed, status=JOB_ERROR, created_at=now)
        self.create_delivery(user=self.user, filename="not-checked.zip")
        unavailable = self.create_delivery(
            user=self.user,
            filename="file-not-found.zip",
        )
        self.create_job(
            delivery=unavailable,
            status="file_not_found",
            created_at=now,
        )
        legacy = self.create_delivery(user=self.user, filename="legacy.zip")
        self.create_job(
            delivery=legacy,
            status="legacy-status",
            created_at=now,
        )

        deleted = self.create_delivery(
            user=self.user,
            filename="deleted.zip",
            is_deleted=True,
        )
        self.create_job(delivery=deleted, status=JOB_OK, created_at=now)

        other_user = get_user_model().objects.create_user(
            username="other-delivery-owner",
            password="test-password",
        )
        hidden = self.create_delivery(user=other_user, filename="hidden.zip")
        self.create_job(delivery=hidden, status=JOB_OK, created_at=now)

        account_access = access_for(self.user)
        # Resolve the account's catalog scope once, then aggregate in one query.
        account_access.operable_product_idents
        with self.assertNumQueries(1):
            summary = summarize_deliveries(account_access)

        self.assertEqual(summary.total, 6)
        self.assertEqual(summary.passed, 1)
        self.assertEqual(summary.in_progress, 1)
        self.assertEqual(summary.failed, 2)
        self.assertEqual(summary.not_checked, 1)
        self.assertEqual(summary.other, 1)
        self.assertEqual(
            summary.as_dict(),
            {
                "total": 6,
                "passed": 1,
                "in_progress": 1,
                "failed": 2,
                "not_checked": 1,
                "other": 1,
            },
        )

    def test_administrator_summary_excludes_legacy_orphan_rows(self):
        administrator = get_user_model().objects.create_user(
            username="delivery-summary-admin",
            password="test-password",
        )
        administrator.groups.add(Group.objects.get(name=Role.ADMIN.value))
        self.create_delivery(user=self.user, filename="visible.zip")
        self.create_delivery(user=None, filename="orphan.zip")

        summary = summarize_deliveries(access_for(administrator))

        self.assertEqual(summary.total, 1)
        self.assertEqual(summary.not_checked, 1)
