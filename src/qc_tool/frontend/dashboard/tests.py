# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from datetime import timedelta
from json import JSONDecodeError
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID

from django.contrib import admin
from django.contrib.auth.models import User
from django.test import SimpleTestCase
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from qc_tool.common import CONFIG
from qc_tool.common import JOB_FAILED
from qc_tool.common import JOB_OK
from qc_tool.common import JOB_RUNNING
from qc_tool.common import JOB_TIMEOUT
from qc_tool.common import JOB_WAITING
from qc_tool.frontend.dashboard.models import ApiUser
from qc_tool.frontend.dashboard.models import AOI_CODE_MAX_LENGTH
from qc_tool.frontend.dashboard.models import Delivery
from qc_tool.frontend.dashboard.models import Job
from qc_tool.frontend.dashboard.models import S3Info
from qc_tool.frontend.dashboard.views import merge_uploaded_chunks


class UploadedChunkMergeTests(SimpleTestCase):
    def test_existing_archive_is_replaced_instead_of_appended(self):
        with TemporaryDirectory() as directory:
            directory = Path(directory)
            target_filepath = directory.joinpath("delivery.zip")
            target_filepath.write_bytes(b"old archive")
            chunk_paths = [directory.joinpath("chunk-1"), directory.joinpath("chunk-2")]
            chunk_paths[0].write_bytes(b"new ")
            chunk_paths[1].write_bytes(b"archive")

            merge_uploaded_chunks(chunk_paths, target_filepath)

            self.assertEqual(b"new archive", target_filepath.read_bytes())
            self.assertFalse(any(chunk_filepath.exists() for chunk_filepath in chunk_paths))

    def test_failed_merge_preserves_existing_archive_and_chunks(self):
        with TemporaryDirectory() as directory:
            directory = Path(directory)
            target_filepath = directory.joinpath("delivery.zip")
            target_filepath.write_bytes(b"existing archive")
            chunk_filepath = directory.joinpath("chunk-1")
            chunk_filepath.write_bytes(b"partial upload")
            missing_chunk_filepath = directory.joinpath("missing-chunk")

            with self.assertRaises(FileNotFoundError):
                merge_uploaded_chunks(
                    [chunk_filepath, missing_chunk_filepath], target_filepath
                )

            self.assertEqual(b"existing archive", target_filepath.read_bytes())
            self.assertTrue(chunk_filepath.exists())
            self.assertFalse(any(directory.glob("*.uploading")))


class BoundaryListingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="boundary-test-user", password="password"
        )
        self.client.force_login(self.user)

    def test_lists_supported_files_and_ignores_appledouble_metadata(self):
        with TemporaryDirectory() as directory:
            boundary_dir = Path(directory)
            raster_dir = boundary_dir.joinpath("raster")
            vector_dir = boundary_dir.joinpath("vector")
            raster_dir.mkdir()
            vector_dir.mkdir()

            raster_dir.joinpath("mask.tif").write_bytes(b"raster")
            raster_dir.joinpath("._mask.tif").write_bytes(b"metadata")
            raster_dir.joinpath("notes.txt").write_text("not a boundary")
            vector_dir.joinpath("boundary.shp").write_bytes(b"shape")
            vector_dir.joinpath("boundary.gpkg").write_bytes(b"geopackage")
            vector_dir.joinpath("._boundary.gpkg").write_bytes(b"metadata")
            vector_dir.joinpath("boundary.dbf").write_bytes(b"sidecar")
            vector_dir.joinpath("directory.gpkg").mkdir()

            with patch.dict(CONFIG, {"boundary_dir": boundary_dir}):
                raster_response = self.client.get(
                    reverse("boundaries_json", args=["raster"])
                )
                vector_response = self.client.get(
                    reverse("boundaries_json", args=["vector"])
                )

            self.assertEqual(200, raster_response.status_code)
            self.assertEqual(
                ["mask.tif"],
                [row["filename"] for row in raster_response.json()],
            )
            self.assertTrue(
                all(row["type"] == "raster" for row in raster_response.json())
            )
            self.assertEqual(200, vector_response.status_code)
            self.assertEqual(
                {"boundary.shp", "boundary.gpkg"},
                {row["filename"] for row in vector_response.json()},
            )
            self.assertTrue(
                all(row["type"] == "vector" for row in vector_response.json())
            )

    def test_unreadable_boundary_does_not_break_listing(self):
        with TemporaryDirectory() as directory:
            boundary_dir = Path(directory)
            raster_dir = boundary_dir.joinpath("raster")
            raster_dir.mkdir()
            raster_dir.joinpath("readable.tif").write_bytes(b"raster")
            raster_dir.joinpath("unreadable.tif").write_bytes(b"raster")
            original_stat = Path.stat

            def guarded_stat(path, *args, **kwargs):
                if path.name == "unreadable.tif":
                    raise PermissionError("unreadable test boundary")
                return original_stat(path, *args, **kwargs)

            with patch.dict(CONFIG, {"boundary_dir": boundary_dir}), patch.object(
                Path, "stat", new=guarded_stat
            ):
                response = self.client.get(
                    reverse("boundaries_json", args=["raster"])
                )

            self.assertEqual(200, response.status_code)
            self.assertEqual(
                ["readable.tif"], [row["filename"] for row in response.json()]
            )


class DeliveryAdminTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="delivery-admin",
            email="delivery-admin@example.com",
            password="password",
        )
        self.s3 = S3Info.objects.create(
            host="s3.example.com",
            access_key="access-key",
            secret_key="secret-key",
            bucketname="delivery-bucket",
            key_prefix="deliveries/",
        )
        self.delivery = Delivery.objects.create(
            user=self.admin_user,
            filename="admin-delivery.zip",
            size_bytes=987654321,
            date_submitted=timezone.now(),
            product_ident="clc2012",
            product_description="CORINE Land Cover 2012",
            aoi_code="ee003l",
            s3=self.s3,
        )
        self.deleted_delivery = Delivery.objects.create(
            user=self.admin_user,
            filename="soft-deleted-delivery.zip",
            size_bytes=1,
            is_deleted=True,
        )
        self.client.force_login(self.admin_user)

    def test_delivery_admin_displays_all_concrete_model_fields(self):
        model_admin = admin.site._registry[Delivery]
        field_names = tuple(field.name for field in Delivery._meta.concrete_fields)

        self.assertEqual(("id", "aoi_code"), model_admin.readonly_fields)
        self.assertEqual(("user", "s3"), model_admin.list_select_related)

        changelist_response = self.client.get(
            reverse("admin:dashboard_delivery_changelist")
        )

        self.assertEqual(200, changelist_response.status_code)
        list_display = tuple(
            "active" if field_name == "is_deleted" else field_name
            for field_name in field_names
        )
        self.assertEqual(
            list_display,
            tuple(model_admin.get_list_display(changelist_response.wsgi_request)),
        )
        self.assertContains(changelist_response, self.delivery.filename)
        self.assertContains(changelist_response, self.deleted_delivery.filename)
        self.assertContains(changelist_response, self.delivery.product_ident)
        self.assertContains(changelist_response, self.delivery.product_description)
        self.assertContains(changelist_response, self.delivery.aoi_code)
        self.assertContains(changelist_response, str(self.delivery.size_bytes))

        change_response = self.client.get(
            reverse("admin:dashboard_delivery_change", args=[self.delivery.id])
        )

        self.assertEqual(200, change_response.status_code)
        self.assertEqual(
            field_names,
            tuple(model_admin.get_fields(change_response.wsgi_request, self.delivery)),
        )
        self.assertContains(change_response, self.delivery.filename)
        self.assertContains(change_response, self.delivery.aoi_code)

    def test_delivery_admin_displays_positive_active_state_icons(self):
        model_admin = admin.site._registry[Delivery]

        self.assertIs(True, model_admin.active(self.delivery))
        self.assertIs(False, model_admin.active(self.deleted_delivery))

        response = self.client.get(reverse("admin:dashboard_delivery_changelist"))

        self.assertEqual(200, response.status_code)
        self.assertContains(response, "Active")
        self.assertContains(response, "icon-yes.svg", count=1)
        self.assertContains(response, "icon-no.svg", count=1)


class JobAdminTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="job-admin",
            email="job-admin@example.com",
            password="password",
        )
        self.delivery = Delivery.objects.create(
            filename="admin-delivery.zip",
            size_bytes=1,
            user=self.admin_user,
        )
        self.job = Job.objects.create(
            delivery=self.delivery,
            product_ident="clc2012",
            product_description="CORINE Land Cover 2012",
            aoi_code="ee003l",
        )
        self.client.force_login(self.admin_user)

    def test_job_admin_displays_all_concrete_model_fields(self):
        model_admin = admin.site._registry[Job]
        field_names = tuple(field.name for field in Job._meta.concrete_fields)
        readonly_field_names = tuple(
            field.name for field in Job._meta.concrete_fields if not field.editable
        )

        self.assertEqual(readonly_field_names, model_admin.readonly_fields)

        changelist_response = self.client.get(reverse("admin:dashboard_job_changelist"))

        self.assertEqual(200, changelist_response.status_code)
        self.assertEqual(
            field_names,
            tuple(model_admin.get_list_display(changelist_response.wsgi_request)),
        )
        self.assertContains(changelist_response, "ee003l")

        change_response = self.client.get(
            reverse("admin:dashboard_job_change", args=[self.job.job_uuid])
        )

        self.assertEqual(200, change_response.status_code)
        self.assertEqual(
            field_names,
            tuple(model_admin.get_fields(change_response.wsgi_request, self.job)),
        )
        self.assertContains(change_response, str(self.job.job_uuid))
        self.assertContains(change_response, "ee003l")


class JobAoiPersistenceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="aoi-test-user", password="password")
        self.delivery = Delivery.objects.create(filename="delivery.zip", size_bytes=1, user=self.user)

    def create_job(self, **kwargs):
        values = {
            "delivery": self.delivery,
            "product_ident": "clc2012",
            "product_description": "CORINE Land Cover 2012",
        }
        values.update(kwargs)
        return Job.objects.create(**values)

    @patch("qc_tool.frontend.dashboard.models.load_job_result")
    def test_terminal_status_persists_aoi_code(self, load_result):
        load_result.return_value = {"aoi_code": "mt"}
        job = self.create_job()

        job.update_status(JOB_OK)

        job.refresh_from_db()
        self.delivery.refresh_from_db()
        self.assertEqual(JOB_OK, job.job_status)
        self.assertEqual("mt", job.aoi_code)
        self.assertEqual("mt", self.delivery.aoi_code)
        self.assertIsNotNone(job.date_finished)
        load_result.assert_called_once_with(str(job.job_uuid))

    @patch("qc_tool.frontend.dashboard.models.load_job_result")
    def test_failed_status_also_persists_aoi_code(self, load_result):
        load_result.return_value = {"aoi_code": " EE003L1 "}
        job = self.create_job()

        job.update_status(JOB_FAILED)

        job.refresh_from_db()
        self.delivery.refresh_from_db()
        self.assertEqual(JOB_FAILED, job.job_status)
        self.assertEqual("ee003l", job.aoi_code)
        self.assertEqual("ee003l", self.delivery.aoi_code)

    @patch("qc_tool.frontend.dashboard.models.load_job_result")
    def test_nonterminal_status_does_not_load_result_metadata(self, load_result):
        for job_status in (JOB_WAITING, JOB_RUNNING):
            with self.subTest(job_status=job_status):
                job = self.create_job()
                job.update_status(job_status)
                job.refresh_from_db()
                self.assertEqual(job_status, job.job_status)
                self.assertIsNone(job.aoi_code)
                self.assertIsNone(job.date_finished)
                self.delivery.refresh_from_db()
                self.assertIsNone(self.delivery.aoi_code)
        load_result.assert_not_called()

    def test_unreadable_result_does_not_block_terminal_status(self):
        errors = (
            FileNotFoundError("result not found"),
            JSONDecodeError("invalid result", "", 0),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__):
                job = self.create_job()
                with patch("qc_tool.frontend.dashboard.models.load_job_result", side_effect=error):
                    job.update_status(JOB_TIMEOUT)
                job.refresh_from_db()
                self.assertEqual(JOB_TIMEOUT, job.job_status)
                self.assertIsNone(job.aoi_code)
                self.assertIsNotNone(job.date_finished)

    @patch("qc_tool.frontend.dashboard.models.load_job_result")
    def test_date_finished_is_write_once(self, load_result):
        load_result.return_value = {"aoi_code": "mt"}
        job = self.create_job()
        job.update_status(JOB_OK)
        job.refresh_from_db()
        first_finished = job.date_finished

        job.update_status(JOB_FAILED)

        job.refresh_from_db()
        self.assertEqual(first_finished, job.date_finished)

    def test_invalid_aoi_metadata_is_ignored(self):
        invalid_results = (
            [],
            {},
            {"aoi_code": None},
            {"aoi_code": ""},
            {"aoi_code": 123},
            {"aoi_code": "x" * (AOI_CODE_MAX_LENGTH + 1)},
        )
        for result in invalid_results:
            with self.subTest(result=result):
                job = self.create_job()
                self.assertEqual([], job.apply_result_metadata(result))
                self.assertIsNone(job.aoi_code)

    @patch("qc_tool.frontend.dashboard.models.load_job_result")
    def test_missing_metadata_does_not_erase_persisted_aoi(self, load_result):
        load_result.return_value = {}
        job = self.create_job(aoi_code="mt")
        self.delivery.aoi_code = "mt"
        self.delivery.save(update_fields=["aoi_code"])

        job.update_status(JOB_FAILED)

        job.refresh_from_db()
        self.delivery.refresh_from_db()
        self.assertEqual("mt", job.aoi_code)
        self.assertEqual("mt", self.delivery.aoi_code)

    @patch("qc_tool.frontend.dashboard.models.load_job_result")
    def test_explicit_null_metadata_clears_persisted_aoi(self, load_result):
        load_result.return_value = {"aoi_code": None}
        job = self.create_job(aoi_code="mt")
        self.delivery.aoi_code = "mt"
        self.delivery.save(update_fields=["aoi_code"])

        job.update_status(JOB_FAILED)

        job.refresh_from_db()
        self.delivery.refresh_from_db()
        self.assertIsNone(job.aoi_code)
        self.assertIsNone(self.delivery.aoi_code)

    @patch("qc_tool.frontend.dashboard.models.load_job_result")
    def test_older_job_cannot_overwrite_latest_delivery_aoi(self, load_result):
        now = timezone.now()
        older_job = self.create_job(date_created=now - timedelta(minutes=1))
        latest_job = self.create_job(date_created=now)
        results = {
            str(older_job.job_uuid): {"aoi_code": "EE003L1"},
            str(latest_job.job_uuid): {"aoi_code": "DU001A"},
        }
        load_result.side_effect = results.__getitem__

        latest_job.update_status(JOB_OK)
        older_job.update_status(JOB_FAILED)

        older_job.refresh_from_db()
        latest_job.refresh_from_db()
        self.delivery.refresh_from_db()
        self.assertEqual("ee003l", older_job.aoi_code)
        self.assertEqual("du001", latest_job.aoi_code)
        self.assertEqual("du001", self.delivery.aoi_code)

    def test_creating_latest_job_resets_delivery_aoi_until_result_exists(self):
        self.delivery.aoi_code = "mt"
        self.delivery.save(update_fields=["aoi_code"])

        job_uuid = self.delivery.create_job("clc2012", None)

        self.delivery.refresh_from_db()
        job = Job.objects.get(job_uuid=UUID(job_uuid))
        self.assertEqual("clc2012", self.delivery.product_ident)
        self.assertIsNone(self.delivery.aoi_code)
        self.assertIsNone(job.aoi_code)

    def test_job_history_endpoints_expose_persisted_aoi_code(self):
        first_job = self.create_job(aoi_code="ee003l")
        second_job = self.create_job(aoi_code="du001")
        self.client.force_login(self.user)

        dashboard_response = self.client.get(reverse("job_history_json", args=[self.delivery.id]))

        self.assertEqual(200, dashboard_response.status_code)
        dashboard_jobs = {
            str(UUID(job["job_uuid"])): job["aoi_code"]
            for job in dashboard_response.json()
        }
        self.assertEqual({
            str(first_job.job_uuid): "ee003l",
            str(second_job.job_uuid): "du001",
        }, dashboard_jobs)

        ApiUser.objects.create(user=self.user, api_key="aoi-test-key")
        api_response = self.client.get(
            reverse("api_job_history", args=[self.delivery.id]),
            {"apikey": "aoi-test-key"},
        )

        self.assertEqual(200, api_response.status_code)
        api_jobs = {
            str(UUID(job["job_uuid"])): job["aoi_code"]
            for job in api_response.json()["data"]
        }
        self.assertEqual({
            str(first_job.job_uuid): "ee003l",
            str(second_job.job_uuid): "du001",
        }, api_jobs)

    @patch("qc_tool.frontend.dashboard.views.compile_job_report_data")
    def test_result_page_displays_product_identifier_and_aoi_code(self, compile_report):
        job = self.create_job(aoi_code="ee003l")
        compile_report.return_value = {
            "job_uuid": str(job.job_uuid),
            "description": job.product_description,
            "product_ident": job.product_ident,
            "aoi_code": job.aoi_code,
            "reference_year": "2012",
            "filename": self.delivery.filename,
            "job_start_date": None,
            "job_finish_date": None,
            "status": JOB_OK,
            "steps": [],
        }
        self.client.force_login(self.user)

        response = self.client.get(reverse("show_result", args=[job.job_uuid]))

        self.assertEqual(200, response.status_code)
        self.assertContains(response, "Product ID")
        self.assertContains(response, "clc2012")
        self.assertContains(response, "AOI Code")
        self.assertContains(response, "ee003l")
        self.assertContains(response, 'data-toggle="tooltip"')
        self.assertContains(response, 'aria-label="About AOI Code"')
        self.assertContains(
            response,
            "AOI stands for Area of Interest. The code identifies the geographic area associated with this QC job.",
        )

    def test_delivery_list_endpoints_expose_only_canonical_aoi_code(self):
        self.delivery.product_ident = "clc2012"
        self.delivery.aoi_code = "ee003l"
        self.delivery.save(update_fields=["product_ident", "aoi_code"])
        other_user = User.objects.create_user(username="other-aoi-user", password="password")
        Delivery.objects.create(
            filename="other.zip",
            size_bytes=1,
            user=other_user,
            aoi_code="du001",
        )
        self.client.force_login(self.user)

        dashboard_response = self.client.get(reverse("deliveries_json"))

        self.assertEqual(200, dashboard_response.status_code)
        dashboard_rows = dashboard_response.json()["rows"]
        self.assertEqual(1, len(dashboard_rows))
        self.assertEqual("clc2012", dashboard_rows[0]["product_ident"])
        self.assertEqual("ee003l", dashboard_rows[0]["aoi_code"])

        ApiUser.objects.create(user=self.user, api_key="aoi-delivery-key")
        api_response = self.client.get(
            reverse("api_delivery_list"),
            {"apikey": "aoi-delivery-key"},
        )

        self.assertEqual(200, api_response.status_code)
        api_deliveries = api_response.json()["deliveries"]
        self.assertEqual(1, len(api_deliveries))
        self.assertEqual("clc2012", api_deliveries[0]["product_ident"])
        self.assertEqual("ee003l", api_deliveries[0]["aoi_code"])

    def test_deleting_latest_job_reprojects_delivery_aoi(self):
        now = timezone.now()
        older_job = self.create_job(date_created=now - timedelta(minutes=1), aoi_code="ee003l")
        latest_job = self.create_job(date_created=now, aoi_code="du001")
        self.delivery.sync_from_latest_job()
        self.client.force_login(self.user)

        response = self.client.post(reverse("job_delete"), {"uuids": str(latest_job.job_uuid)})

        self.assertEqual(200, response.status_code)
        self.delivery.refresh_from_db()
        self.assertTrue(Job.objects.filter(pk=older_job.pk).exists())
        self.assertFalse(Job.objects.filter(pk=latest_job.pk).exists())
        self.assertEqual("ee003l", self.delivery.aoi_code)
