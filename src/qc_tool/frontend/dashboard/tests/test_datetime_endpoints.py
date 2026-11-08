"""Delivery/history UI and API timestamps identify the same stored instant."""

from datetime import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.dateparse import parse_datetime

from qc_tool.common import JOB_OK
from qc_tool.frontend.accounts.services.api_tokens import issue_personal_access_token
from qc_tool.frontend.dashboard.models import Delivery, Job


@override_settings(USE_TZ=False, TIME_ZONE="Europe/Prague", MAINTENANCE_MODE=False)
class DateTimeEndpointTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(username="timestamp-admin")
        self.client.force_login(self.user)
        token = issue_personal_access_token(self.user, "Timestamp endpoint regression")
        self.authorization = {"HTTP_AUTHORIZATION": f"Bearer {token.raw_token}"}
        self.deliveries = []
        for month in (1, 7):
            timestamp = datetime(2026, month, 15, 14, 30)
            delivery = Delivery.objects.create(
                user=self.user, filename=f"timestamp-{month}.zip", size_bytes=1,
                product_ident="clc2018", date_uploaded=timestamp,
            )
            Job.objects.create(
                delivery=delivery, product_ident="clc2018", product_description="CLC",
                job_status=JOB_OK, date_created=timestamp,
                date_started=timestamp, date_finished=None,
            )
            self.deliveries.append(delivery)

    def assert_timestamp(self, value, month):
        offset = "+01:00" if month == 1 else "+02:00"
        self.assertEqual(value, f"2026-{month:02d}-15T14:30:00{offset}")
        self.assertIsNotNone(parse_datetime(value).utcoffset())

    def test_delivery_list_ui_and_api_include_explicit_offsets(self):
        endpoints = (
            ("deliveries_json", "rows", {}),
            ("api_delivery_list", "deliveries", self.authorization),
        )
        for name, row_key, headers in endpoints:
            with self.subTest(endpoint=name):
                response = self.client.get(reverse(name), **headers)
                self.assertEqual(response.status_code, 200)
                rows = response.json()[row_key]
                self.assertEqual(len(rows), 2)
                for row in rows:
                    month = int(row["filename"].split("-")[1].split(".")[0])
                    for field in ("date_uploaded", "date_created", "date_started"):
                        self.assert_timestamp(row[field], month)
                    self.assertIsNone(row["date_finished"])

    def test_job_history_ui_and_api_include_explicit_offsets(self):
        for delivery in self.deliveries:
            month = delivery.date_uploaded.month
            for name, headers in (
                ("job_history_json", {}), ("api_job_history", self.authorization),
            ):
                with self.subTest(endpoint=name, month=month):
                    response = self.client.get(reverse(name, args=(delivery.pk,)), **headers)
                    self.assertEqual(response.status_code, 200)
                    payload = response.json()
                    rows = payload["data"] if name == "api_job_history" else payload
                    self.assertEqual(len(rows), 1)
                    self.assert_timestamp(rows[0]["date_created"], month)
                    self.assert_timestamp(rows[0]["date_started"], month)
                    self.assertIsNone(rows[0]["date_finished"])

    def test_history_envelope_dates_are_also_unambiguous(self):
        delivery = self.deliveries[0]
        response = self.client.get(
            reverse("job_history_json", args=(delivery.pk,)), {"include_delivery": "1"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assert_timestamp(payload["rows"][0]["date_started"], 1)
        uploaded = next(
            fact for fact in payload["delivery_summary"]["facts"]
            if fact["label"] == "Uploaded"
        )
        self.assert_timestamp(uploaded["datetime"], 1)
