import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from qc_tool.frontend.accounts.authorization.roles import Role
from qc_tool.frontend.accounts.models import UserProductGrant
from qc_tool.frontend.accounts.services.api_tokens import (
    issue_personal_access_token,
)
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import Job


class ApiObjectAccessTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="delivery-owner")
        self.manager = user_model.objects.create_user(username="product-reader")
        self.other = user_model.objects.create_user(username="unscoped-reader")
        self.admin = user_model.objects.create_superuser(
            username="api-admin",
            email="admin@example.test",
            password="unused-password",
        )
        self.delivery = Delivery.objects.create(
            user=self.owner,
            filename="clc2012_delivery.zip",
            size_bytes=10,
            product_ident="clc2012",
            product_description="CLC",
        )
        self.job = Job.objects.create(
            delivery=self.delivery,
            product_ident="clc2012",
            product_description="CLC",
        )

        self.manager.groups.add(Group.objects.get(name=Role.PRODUCT_MANAGER.value))
        UserProductGrant.objects.create(
            user=self.manager,
            product_ident="clc2012",
        )

    def authorization(self, user):
        token_number = user.personal_access_tokens.count() + 1
        issued = issue_personal_access_token(
            user,
            f"Object access test {token_number}",
        )
        return f"Bearer {issued.raw_token}"

    def test_delivery_list_uses_token_snapshot_not_later_product_grants(self):
        issued = issue_personal_access_token(
            self.manager,
            "Delivery list scope snapshot",
        )
        UserProductGrant.objects.create(
            user=self.manager,
            product_ident="later_product",
        )
        Delivery.objects.create(
            user=self.owner,
            filename="later_product_delivery.zip",
            size_bytes=10,
            product_ident="later_product",
            product_description="Later product",
        )

        response = self.client.get(
            reverse("api_delivery_list"),
            HTTP_AUTHORIZATION=f"Bearer {issued.raw_token}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(
            [item["filename"] for item in response.json()["deliveries"]],
            ["clc2012_delivery.zip"],
        )

    @patch(
        "qc_tool.frontend.dashboard.views.compile_job_report_data",
        return_value={"status": "ok", "steps": []},
    )
    def test_product_scoped_reader_can_open_a_job_visible_in_its_scope(
        self,
        _compile_report,
    ):
        response = self.client.get(
            reverse("api_job_result", args=(self.job.job_uuid,)),
            HTTP_AUTHORIZATION=self.authorization(self.manager),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["status"], "ok")

        history = self.client.get(
            reverse("api_job_history", args=(self.delivery.pk,)),
            HTTP_AUTHORIZATION=self.authorization(self.manager),
        )
        self.assertEqual(history.status_code, 200)
        self.assertEqual(len(history.json()["data"]), 1)

    @patch("qc_tool.frontend.dashboard.views.compile_job_report_data")
    def test_unscoped_user_receives_json_403_before_report_loading(
        self,
        compile_report,
    ):
        response = self.client.get(
            reverse("api_job_result", args=(self.job.job_uuid,)),
            HTTP_AUTHORIZATION=self.authorization(self.other),
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "object_permission_denied")
        compile_report.assert_not_called()

    @patch(
        "qc_tool.frontend.dashboard.models.Delivery.create_job",
        return_value="00000000000000000000000000000001",
    )
    def test_mutation_remains_owner_or_admin_only(
        self,
        create_job,
    ):
        with TemporaryDirectory() as directory:
            definition = Path(directory) / "clc2012.json"
            definition.write_text('{"steps": []}', encoding="utf-8")
            body = json.dumps(
                {
                    "delivery_id": self.delivery.pk,
                    "product_ident": "clc2012",
                }
            )
            with patch(
                "qc_tool.frontend.dashboard.services.jobs.requests.locate_product_definition",
                return_value=definition,
            ):
                denied = self.client.post(
                    reverse("api_create_job"),
                    data=body,
                    content_type="application/json",
                    HTTP_AUTHORIZATION=self.authorization(self.manager),
                )
                allowed = self.client.post(
                    reverse("api_create_job"),
                    data=body,
                    content_type="application/json",
                    HTTP_AUTHORIZATION=self.authorization(self.admin),
                )

        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["code"], "object_permission_denied")
        self.assertEqual(allowed.status_code, 200)
        create_job.assert_called_once()
