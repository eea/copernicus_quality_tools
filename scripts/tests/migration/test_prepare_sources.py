"""Stdlib checks for mixed-source provenance, credential policy and references."""

import contextlib
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest


from scripts.migration.legacy import prepare_sources as preparation


class MixedSourcePreparationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.user = {name: "" for name in preparation.USER_COLUMNS}
        self.user.update(id="1", username="synthetic-current", password="older-hash-must-not-return",
                         is_superuser="f", is_staff="f", is_active="t", last_login=None,
                         date_joined="2020-01-01T00:00:00+01:00")

    def write_users(self):
        path = self.directory / "current-users.json"
        preparation.write_json(path, {"captured_at": "2026-10-12T00:00:00+02:00",
                                     "users": [{**self.user, "source_groups": [{"id": "1", "name": "obsolete"}]}]})
        return path

    def test_admin_capture_always_disables_password_and_archives_access_metadata(self):
        path = self.write_users()
        original = path.read_bytes()
        users, metadata = preparation.read_current_users(path)
        self.assertEqual(users[0]["password"], "!legacy-admin-export")
        self.assertNotIn("source_groups", users[0])
        self.assertEqual(metadata["source_group_links_not_mapped"], 1)
        self.assertEqual(path.read_bytes(), original)

    def test_incomplete_current_user_capture_fails_without_invented_fields(self):
        self.user.pop("date_joined")
        with self.assertRaisesRegex(preparation.RehearsalError, "missing canonical fields"):
            preparation.read_current_users(self.write_users())

    def test_source_timezone_localizes_dates_and_keeps_raw_capture_unchanged(self):
        self.user.update(source_timezone="Europe/Prague", date_joined="2020-01-01T12:00:00",
                         last_login="2026-07-01T12:00:00")
        path = self.write_users()
        original = path.read_bytes()
        users, metadata = preparation.read_current_users(path)
        self.assertEqual(users[0]["date_joined"], "2020-01-01T12:00:00+01:00")
        self.assertEqual(users[0]["last_login"], "2026-07-01T12:00:00+02:00")
        self.assertNotIn("source_timezone", users[0])
        self.assertEqual(metadata["source_timezones"], ["Europe/Prague"])
        self.assertEqual(metadata["naive_timestamps_localized"], 2)
        self.assertEqual(path.read_bytes(), original)

    def test_naive_dates_require_valid_explicit_source_timezone(self):
        self.user["date_joined"] = "2020-01-01T12:00:00"
        with self.assertRaisesRegex(preparation.RehearsalError, "requires explicit source_timezone"):
            preparation.read_current_users(self.write_users())
        # Use a new source file for the next attempt; evidence is never overwritten.
        (self.directory / "current-users.json").rename(self.directory / "first-attempt.json")
        self.user["source_timezone"] = "Synthetic/Unknown"
        with self.assertRaisesRegex(preparation.RehearsalError, "unsupported source timezone"):
            preparation.read_current_users(self.write_users())

    def test_dst_ambiguity_and_nonexistent_local_times_require_explicit_offset(self):
        self.user["source_timezone"] = "Europe/Prague"
        for index, timestamp in enumerate(("2026-03-29T02:30:00", "2026-10-25T02:30:00")):
            self.user["date_joined"] = timestamp
            with self.assertRaisesRegex(preparation.RehearsalError, "requires an explicit offset"):
                preparation.read_current_users(self.write_users())
            (self.directory / "current-users.json").rename(self.directory / f"dst-attempt-{index}.json")

    def test_copy_interchange_preserves_null_empty_unicode_and_escapes(self):
        destination = self.directory / "prepared.sql"
        original = [None, "", "\\N", "tab\tnew\nline\rquote'", "žluťoučký", "\x01"]
        columns = tuple(f"column{index}" for index in range(len(original)))
        preparation.write_interchange(destination, {"synthetic": [dict(zip(columns, original))]}, {"synthetic": columns})
        parsed = preparation.read_legacy_dump(destination)
        self.assertEqual(list(parsed.tables["synthetic"][0].values()), original)
        self.assertIn(b"NOT a current pg_dump", destination.read_bytes())

    def test_missing_storage_reference_fails_without_clearing_relationship(self):
        delivery = {"id": "1", "user_id": "1", "s3_id": "missing"}
        tables = {"auth_user": [self.user], "dashboard_s3info": [],
                  "dashboard_delivery": [delivery], "dashboard_job": []}
        with self.assertRaisesRegex(preparation.RehearsalError, "storage absent"):
            preparation.validate_relationships(tables)
        self.assertEqual(delivery["s3_id"], "missing")

    def test_end_to_end_preparation_keeps_sources_and_clears_stale_access(self):
        older = self.directory / "older.sql"
        tables = {"auth_user": [self.user], "auth_user_groups": [{"id": "1", "user_id": "1", "group_id": "1"}],
                  "auth_user_user_permissions": [], "auth_group_permissions": [],
                  "dashboard_s3info": [], "django_admin_log": []}
        columns = {"auth_user": preparation.USER_COLUMNS, "auth_user_groups": ("id", "user_id", "group_id"),
                   "auth_user_user_permissions": ("id", "user_id", "permission_id"),
                   "auth_group_permissions": ("id", "group_id", "permission_id"),
                   "dashboard_s3info": ("id",), "django_admin_log": ("id", "user_id")}
        preparation.write_interchange(older, tables, columns)
        delivery_csv = self.directory / "delivery.csv"
        job_csv = self.directory / "job.csv"
        for path, names in ((delivery_csv, preparation.DELIVERY_COLUMNS), (job_csv, preparation.JOB_COLUMNS)):
            with path.open("w", newline="", encoding="utf-8") as stream:
                csv.writer(stream).writerow(names)
        users_json = self.write_users()
        originals = {path: path.read_bytes() for path in (older, delivery_csv, job_csv, users_json)}
        destination = self.directory / "prepared"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = preparation.main([
                "--older-dump", str(older), "--deliveries-csv", str(delivery_csv),
                "--jobs-csv", str(job_csv), "--current-users-json", str(users_json),
                "--output-dir", str(destination),
            ])
        self.assertEqual(result, 0)
        for path, original in originals.items():
            self.assertEqual(path.read_bytes(), original)
        parsed = preparation.read_legacy_dump(destination / "prepared-import.sql")
        self.assertEqual(parsed.tables["auth_user"][0]["password"], "!legacy-admin-export")
        self.assertEqual(parsed.tables["auth_user_groups"], [])
        manifest = json.loads((destination / "source-preparation-manifest.json").read_text())
        self.assertEqual(manifest["kind"], "mixed_available_history_import_interchange")
        self.assertTrue(manifest["original_sources_unchanged"])
        self.assertEqual(manifest["stale_access_links_cleared"]["auth_user_groups"], 1)
        self.assertNotIn("synthetic-current", output.getvalue())
        self.assertNotIn("older-hash", output.getvalue())


if __name__ == "__main__":
    unittest.main()
