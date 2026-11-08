"""Timezone contracts for JSON containing legacy database datetimes."""

from datetime import date, datetime, timezone as datetime_timezone
import json
from uuid import UUID

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from qc_tool.frontend.http_payloads import DatabaseDateTimeJSONEncoder


@override_settings(USE_TZ=False, TIME_ZONE="Europe/Prague")
class DatabaseDateTimeJSONTests(SimpleTestCase):
    def encode(self, value):
        return json.loads(json.dumps(value, cls=DatabaseDateTimeJSONEncoder))

    def test_naive_database_dates_include_winter_and_summer_offsets(self):
        for month, offset in ((1, "+01:00"), (7, "+02:00")):
            with self.subTest(month=month):
                self.assertEqual(
                    self.encode(datetime(2026, month, 15, 14, 30)),
                    f"2026-{month:02d}-15T14:30:00{offset}",
                )

    def test_aware_utc_instant_is_not_reinterpreted(self):
        self.assertEqual(
            self.encode(datetime(2026, 1, 15, 13, 30, tzinfo=datetime_timezone.utc)),
            "2026-01-15T13:30:00Z",
        )

    def test_request_timezone_does_not_change_database_wall_time(self):
        with timezone.override("America/New_York"):
            self.assertEqual(
                self.encode(datetime(2026, 7, 15, 14, 30)),
                "2026-07-15T14:30:00+02:00",
            )

    def test_none_and_original_report_strings_are_preserved(self):
        value = {"date_finished": None, "job_start_date": "2026-01-15T13:30:00Z"}
        self.assertEqual(self.encode(value), value)

    def test_other_types_keep_django_encoding(self):
        identifier = UUID("2bf7a78f-af58-4db4-bafc-a903199b4605")
        self.assertEqual(
            self.encode({"id": identifier, "date": date(2026, 1, 15)}),
            {"id": str(identifier), "date": "2026-01-15"},
        )
