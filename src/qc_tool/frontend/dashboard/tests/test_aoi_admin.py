from django.contrib import admin
from django.test import SimpleTestCase

from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import Job


class AoiAdminBoundaryTests(SimpleTestCase):
    def test_delivery_aoi_is_not_editable_in_admin(self):
        delivery_admin = admin.site._registry[Delivery]

        self.assertIn("aoi_code", delivery_admin.readonly_fields)

    def test_job_admin_cannot_bypass_lifecycle_services(self):
        job_admin = admin.site._registry[Job]

        self.assertEqual(
            set(job_admin.readonly_fields),
            {field.name for field in Job._meta.fields},
        )
        self.assertFalse(job_admin.has_add_permission(None))
        self.assertFalse(job_admin.has_change_permission(None))
        self.assertFalse(job_admin.has_delete_permission(None))
