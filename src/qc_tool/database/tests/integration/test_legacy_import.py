"""Rehearse the major-release converter with synthetic legacy records only."""

from copy import deepcopy
from datetime import datetime
import json
from unittest.mock import patch
from uuid import UUID

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Group
from django.contrib.sessions.models import Session
from django.db import connection
from django.db.models.query import QuerySet
from django.test import TestCase, override_settings

from qc_tool.common import JOB_LOST
from qc_tool.database.legacy.dump import LegacyDump
from qc_tool.database.legacy.importer import apply_import, prepare_import
from qc_tool.frontend.accounts.models import PersonalAccessToken, UserProductGrant, UserProfile
from qc_tool.frontend.dashboard.models import (
    Delivery, DeliverySubmission, Job, Product, ProductRelease, ProductUnit,
    QcDefinition, S3Info,
)


_COLUMNS = {
    "auth_group": ("id", "name"),
    "auth_group_permissions": ("id", "group_id", "permission_id"),
    "auth_permission": ("id", "name", "content_type_id", "codename"),
    "auth_user": ("id", "password", "last_login", "is_superuser", "username", "first_name", "last_name", "email", "is_staff", "is_active", "date_joined"),
    "auth_user_groups": ("id", "user_id", "group_id"),
    "auth_user_user_permissions": ("id", "user_id", "permission_id"),
    "dashboard_apiuser": ("id", "api_key", "user_id"),
    "dashboard_delivery": ("id", "filename", "product_ident", "date_uploaded", "date_submitted", "user_id", "product_description", "size_bytes", "is_deleted", "s3_id", "aoi_code"),
    "dashboard_job": ("job_uuid", "date_created", "date_started", "date_finished", "job_status", "product_ident", "skip_steps", "worker_url", "delivery_id", "product_description", "aoi_code"),
    "dashboard_s3info": ("id", "host", "access_key", "secret_key", "bucketname", "key_prefix"),
    "dashboard_userprofile": ("id", "country", "user_id", "product_family"),
    "django_admin_log": ("id", "action_time", "object_id", "object_repr", "action_flag", "change_message", "content_type_id", "user_id"),
    "django_content_type": ("id", "app_label", "model"),
    "django_migrations": ("id", "app", "name", "applied"),
    "django_session": ("session_key", "session_data", "expire_date"),
}


def synthetic_legacy_dump(password_hash):
    tables = {name: [] for name in _COLUMNS}
    tables["auth_user"] = [{
        "id": "47", "password": password_hash, "last_login": "2024-06-01 12:00:00+00",
        "is_superuser": "f", "username": "legacy-synthetic-owner", "first_name": "Test",
        "last_name": "Person", "email": "legacy-owner@example.invalid", "is_staff": "f",
        "is_active": "t", "date_joined": "2024-01-01 12:00:00+00",
    }]
    tables["dashboard_userprofile"] = [{
        "id": "83", "country": "Synthetic region", "user_id": "47", "product_family": "Legacy family",
    }]
    tables["dashboard_s3info"] = [{
        "id": "701", "host": "https://storage.example.invalid", "access_key": "synthetic-access-secret",
        "secret_key": "synthetic-storage-secret", "bucketname": "synthetic-bucket", "key_prefix": "legacy/object.zip",
    }]
    tables["dashboard_delivery"] = [{
        "id": "901", "filename": "legacy.zip", "product_ident": "legacy-product",
        "date_uploaded": "2024-06-01 12:00:00+00", "date_submitted": "2024-06-01 12:03:00+00",
        "user_id": "47", "product_description": "Historical product description", "size_bytes": "1234",
        "is_deleted": "f", "s3_id": "701", "aoi_code": "007",
    }, {
        "id": "902", "filename": "legacy.zip", "product_ident": "legacy-product",
        "date_uploaded": "2024-06-02 12:00:00+00", "date_submitted": None,
        "user_id": "47", "product_description": "Historical product description", "size_bytes": "0",
        "is_deleted": "t", "s3_id": None, "aoi_code": None,
    }]
    tables["dashboard_job"] = [{
        "job_uuid": str(UUID(int=1001)), "date_created": "2024-06-01 12:00:30+00",
        "date_started": "2024-06-01 12:01:00+00", "date_finished": "2024-06-01 12:02:00+00",
        "job_status": "ok", "product_ident": "legacy-product", "skip_steps": "archive_check",
        "worker_url": "https://worker.example.invalid", "delivery_id": "901",
        "product_description": "Historical product description", "aoi_code": "007",
    }]
    tables["dashboard_apiuser"] = [{"id": "90", "api_key": "synthetic-api-secret", "user_id": "47"}]
    tables["django_session"] = [{
        "session_key": "synthetic-session-key", "session_data": "synthetic-session-secret",
        "expire_date": "2024-06-10 12:00:00+00",
    }]
    return LegacyDump(tables=tables, columns=_COLUMNS, source_sha256="a" * 64, source_size_bytes=123)


@override_settings(USE_TZ=False, TIME_ZONE="Europe/Prague")
class LegacyImportTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password_hash = make_password("synthetic-password-only")

    def setUp(self):
        self.dump = synthetic_legacy_dump(self.password_hash)

    def apply(self, dump=None):
        return apply_import(
            prepare_import(dump or self.dump), database="default",
            target_database=str(connection.settings_dict["NAME"]),
        )

    def test_prepare_does_not_query_or_write_the_target(self):
        with self.assertNumQueries(0):
            plan = prepare_import(self.dump)
        self.assertIsInstance(plan.report, dict)
        self.assertFalse(get_user_model().objects.exists())
        self.assertFalse(Delivery.objects.exists())

    def test_preserves_identity_password_profile_and_required_role(self):
        self.apply()
        user = get_user_model().objects.get(pk=47)
        self.assertEqual(user.username, "legacy-synthetic-owner")
        self.assertEqual(user.email, "legacy-owner@example.invalid")
        self.assertEqual(user.password, self.password_hash)
        self.assertTrue(user.check_password("synthetic-password-only"))
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(user.date_joined, datetime(2024, 1, 1, 13))
        self.assertEqual(user.last_login, datetime(2024, 6, 1, 14))
        self.assertEqual(set(user.groups.values_list("name", flat=True)), {"default"})
        profile = UserProfile.objects.get(user=user)
        self.assertEqual(profile.pk, 83)
        self.assertEqual(profile.country, "Synthetic region")
        self.assertEqual(profile.product_family, "Legacy family")
        self.assertFalse(UserProductGrant.objects.exists())

    def test_preserves_submitted_delivery_and_job_without_inventing_receipts(self):
        self.apply()
        delivery = Delivery.objects.get(pk=901)
        job = Job.objects.get(pk=UUID(int=1001))
        self.assertEqual(delivery.user_id, 47)
        self.assertEqual(delivery.s3_id, 701)
        self.assertEqual(delivery.filename, "legacy.zip")
        self.assertEqual(delivery.size_bytes, 1234)
        self.assertEqual(delivery.product_ident, "legacy-product")
        self.assertEqual(delivery.product_description, "Historical product description")
        self.assertEqual(delivery.date_uploaded, datetime(2024, 6, 1, 14))
        self.assertEqual(delivery.date_submitted, datetime(2024, 6, 1, 14, 3))
        self.assertIsNone(delivery.get_submittable_job())
        self.assertEqual(job.delivery_id, delivery.pk)
        self.assertEqual(job.job_status, "ok")
        self.assertEqual(job.date_created, datetime(2024, 6, 1, 14, 0, 30))
        self.assertEqual(job.date_started, datetime(2024, 6, 1, 14, 1))
        self.assertEqual(job.date_finished, datetime(2024, 6, 1, 14, 2))
        self.assertEqual(job.skip_steps, "archive_check")
        for model in (DeliverySubmission, Product, ProductRelease, ProductUnit, QcDefinition):
            with self.subTest(model=model.__name__):
                self.assertFalse(model.objects.exists())

    def test_preserves_duplicate_filenames_and_deleted_history(self):
        self.apply()
        self.assertEqual(Delivery.objects.filter(filename="legacy.zip").count(), 2)
        deleted = Delivery.objects.get(pk=902)
        self.assertTrue(deleted.is_deleted)
        self.assertEqual(deleted.size_bytes, 0)
        self.assertIsNone(deleted.date_submitted)
        self.assertIsNone(deleted.s3_id)

    def test_legacy_aoi_is_display_metadata_without_verified_provenance(self):
        self.apply()
        delivery = Delivery.objects.get(pk=901)
        job = Job.objects.get(pk=UUID(int=1001))
        self.assertEqual(delivery.product_unit_code, "7")
        self.assertEqual(job.product_unit_code, "7")
        self.assertIsNone(delivery.submitted_product_unit_code)
        self.assertIsNone(job.submitted_product_unit_code)
        self.assertFalse(delivery.content_sha256)
        self.assertFalse(job.input_sha256)
        self.assertIsNone(job.result_metadata)
        self.assertFalse(job.result_sha256)
        self.assertIsNone(job.product_release_id)
        self.assertIsNone(job.qc_definition_id)
        self.assertIsNone(job.requested_by_id)
        self.assertFalse(job.requested_by_username)
        self.assertEqual(job.request_source, "legacy")

    def test_preserves_storage_coordinates_but_does_not_restore_credentials_or_sessions(self):
        self.apply()
        source = S3Info.objects.get(pk=701)
        self.assertEqual(source.host, "https://storage.example.invalid")
        self.assertEqual(source.bucketname, "synthetic-bucket")
        self.assertEqual(source.key_prefix, "legacy/object.zip")
        self.assertEqual(source.access_key, "")
        self.assertEqual(source.secret_key, "")
        self.assertFalse(PersonalAccessToken.objects.exists())
        self.assertFalse(Session.objects.exists())

    def test_pending_legacy_jobs_are_never_imported_as_runnable(self):
        for index, state in enumerate(("waiting", "running"), start=2001):
            job = deepcopy(self.dump.tables["dashboard_job"][0])
            job.update(job_uuid=str(UUID(int=index)), job_status=state, date_finished=None)
            self.dump.tables["dashboard_job"].append(job)
        self.apply()
        self.assertEqual(set(Job.objects.exclude(pk=UUID(int=1001)).values_list("job_status", flat=True)), {JOB_LOST})

    def test_empty_catalog_does_not_make_an_existing_account_database_a_valid_target(self):
        existing = get_user_model().objects.create_user(username="existing-local-account")
        self.assertFalse(Product.objects.exists())
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(list(get_user_model().objects.values_list("pk", flat=True)), [existing.pk])
        self.assertFalse(Delivery.objects.exists())

    def test_target_with_business_data_but_no_users_is_rejected(self):
        Delivery.objects.create(filename="existing-history.zip", size_bytes=0)
        with self.assertRaises(ValueError):
            self.apply()
        self.assertFalse(get_user_model().objects.exists())
        self.assertEqual(Delivery.objects.count(), 1)

    def test_target_database_confirmation_must_match_exactly(self):
        plan = prepare_import(self.dump)
        for name in ("", str(connection.settings_dict["NAME"]) + "-different"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                apply_import(plan, target_database=name)
        self.assertFalse(get_user_model().objects.exists())
        self.assertFalse(Delivery.objects.exists())

    def test_second_import_is_rejected_without_changing_the_first(self):
        self.apply()
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(Delivery.objects.count(), 2)
        self.assertEqual(Job.objects.count(), 1)

    def test_late_write_failure_rolls_back_users_deliveries_and_storage(self):
        original_bulk_create = QuerySet.bulk_create

        def fail_job_write(queryset, *args, **kwargs):
            if queryset.model is Job:
                raise RuntimeError("Synthetic write failure")
            return original_bulk_create(queryset, *args, **kwargs)

        with patch.object(QuerySet, "bulk_create", fail_job_write):
            with self.assertRaisesRegex(RuntimeError, "Synthetic write failure"):
                self.apply()
        for model in (get_user_model(), UserProfile, Delivery, Job, S3Info):
            with self.subTest(model=model.__name__):
                self.assertFalse(model.objects.exists())

    def test_generated_primary_keys_follow_retained_legacy_ids(self):
        self.apply()
        user = get_user_model().objects.create_user(username="post-import-user")
        source = S3Info.objects.create(host="", access_key="", secret_key="", bucketname="", key_prefix="")
        delivery = Delivery.objects.create(user=user, filename="new.zip", size_bytes=1)
        profile = UserProfile.objects.create(user=user)
        self.assertGreater(user.pk, 47)
        self.assertGreater(source.pk, 701)
        self.assertGreater(delivery.pk, 902)
        self.assertGreater(profile.pk, 83)

    def test_reports_do_not_contain_source_personal_data_or_secrets(self):
        plan = prepare_import(self.dump)
        reports = json.dumps([plan.report, apply_import(plan, target_database=str(connection.settings_dict["NAME"]))])
        for private_value in (
            self.password_hash, "legacy-synthetic-owner", "legacy-owner@example.invalid",
            "synthetic-access-secret", "synthetic-storage-secret", "synthetic-api-secret", "synthetic-session-secret",
        ):
            with self.subTest(value=private_value):
                self.assertNotIn(private_value, reports)

    def test_framework_permission_and_role_bootstrap_is_allowed(self):
        Group.objects.get_or_create(name="default")
        self.apply()
        self.assertTrue(get_user_model().objects.filter(pk=47).exists())

    def test_invalid_legacy_foreign_key_is_rejected_before_writing(self):
        self.dump.tables["dashboard_job"][0]["delivery_id"] = "999999"
        with self.assertNumQueries(0), self.assertRaises(ValueError):
            prepare_import(self.dump)
        self.assertFalse(get_user_model().objects.exists())

    def test_invalid_delivery_size_is_rejected_before_writing(self):
        self.dump.tables["dashboard_delivery"][0]["size_bytes"] = "-1"
        with self.assertNumQueries(0), self.assertRaises(ValueError):
            prepare_import(self.dump)
        self.assertFalse(get_user_model().objects.exists())

    def test_admin_history_preserves_actor_time_text_and_maps_content_types_by_name(self):
        self.dump.tables["django_content_type"] = [
            {"id": "501", "app_label": "auth", "model": "user"},
            {"id": "502", "app_label": "dashboard", "model": "removed_legacy_model"},
        ]
        self.dump.tables["django_admin_log"] = [{
            "id": "601", "action_time": "2024-06-01 12:00:00+00", "object_id": "47",
            "object_repr": "Synthetic account", "action_flag": "2", "change_message": "Historical audit text",
            "content_type_id": "501", "user_id": "47",
        }, {
            "id": "602", "action_time": "2024-06-01 12:01:00+00", "object_id": "99",
            "object_repr": "Synthetic deleted record", "action_flag": "3", "change_message": "Historical removal",
            "content_type_id": "502", "user_id": "47",
        }]
        self.apply()
        account_event = LogEntry.objects.get(pk=601)
        self.assertEqual(account_event.user_id, 47)
        self.assertEqual(account_event.action_time, datetime(2024, 6, 1, 14))
        self.assertEqual(account_event.object_id, "47")
        self.assertEqual(account_event.object_repr, "Synthetic account")
        self.assertEqual(account_event.change_message, "Historical audit text")
        self.assertEqual(account_event.content_type.natural_key(), ("auth", "user"))
        removed_event = LogEntry.objects.get(pk=602)
        self.assertIsNone(removed_event.content_type_id)
        self.assertEqual(removed_event.object_id, "99")
        self.assertEqual(removed_event.change_message, "Historical removal")

    def test_unknown_legacy_groups_preserve_membership_without_becoming_management_roles(self):
        self.dump.tables["auth_group"] = [{"id": "51", "name": "historical-team"}]
        self.dump.tables["auth_user_groups"] = [{"id": "61", "user_id": "47", "group_id": "51"}]
        self.apply()
        user = get_user_model().objects.get(pk=47)
        self.assertEqual(set(user.groups.values_list("name", flat=True)), {"default", "legacy:historical-team"})
        self.assertFalse(Group.objects.get(name="legacy:historical-team").permissions.exists())
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
