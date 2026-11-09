"""Artifact and Admin readers consume both retained job layouts safely."""

from io import BytesIO
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

from django.test import SimpleTestCase

from qc_tool.frontend.dashboard.services.artifacts import ArtifactUnavailable, open_job_attachment, open_job_report
from qc_tool.frontend.dashboard.services.storage_admin import downloads, files
from qc_tool.frontend.dashboard.services.tests.test_storage_admin import StorageFixture
from qc_tool.jobs import create_job_paths


class JobArtifactLayoutTests(StorageFixture, SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.canonical = create_job_paths(self.work, str(uuid4()))
        self.canonical.result_path.write_bytes(b'{"report_filename":"report.pdf"}')
        self.canonical.report_path("report.pdf").write_bytes(b"new PDF")
        (self.canonical.output_dir / "attachment.txt").write_bytes(b"new output")
        (self.job_directory / "output.d").mkdir()
        (self.job_directory / "output.d/attachment.txt").write_bytes(b"old output")
        (self.job_directory / "report.pdf").write_bytes(b"old PDF")
        (self.job_directory / "result.json").write_bytes(b"{}")

    def test_downloads_bind_to_exact_report_and_attachment_in_each_layout(self):
        for identity, output, report in ((self.job_id, b"old output", b"old PDF"),
                                         (self.canonical.job_uuid, b"new output", b"new PDF")):
            with self.subTest(identity=identity):
                with open_job_attachment(identity, "attachment.txt") as stream:
                    self.assertEqual(stream.read(), output)
                stream, filename = open_job_report(identity)
                with stream:
                    self.assertEqual(stream.read(), report)
                self.assertEqual(filename, "report.pdf")

    def test_admin_lists_and_streams_exact_nested_canonical_names(self):
        names = {e["name"] for e in files.list_entries("jobs")["entries"]}
        self.assertTrue({self.job_directory.name, self.canonical.directory.name} <= names)
        relative = self.canonical.directory.name
        with files.open_file("jobs", relative + "/job.json") as stream:
            self.assertEqual(stream.read(), self.canonical.metadata_path.read_bytes())
        plan = downloads.prepare_zip("jobs", [relative])
        with ZipFile(BytesIO(b"".join(downloads.stream_zip(plan)))) as archive:
            self.assertEqual(archive.read("files/" + relative + "/reports/report.pdf"), b"new PDF")
            self.assertEqual(archive.read("files/" + relative + "/outputs/attachment.txt"), b"new output")
        for suffix in ("result.json", "job.json", "specification/source.json"):
            self.assertTrue(files.quarantine_reason("jobs", relative + "/" + suffix, {"kind": "file"}))

    def test_links_and_ambiguous_uuid_layouts_fail_closed(self):
        target = self.canonical.output_dir / "attachment.txt"
        target.unlink()
        target.symlink_to(self.job_directory / "report.pdf")
        with self.assertRaises(ArtifactUnavailable):
            open_job_attachment(self.canonical.job_uuid, "attachment.txt")
        (self.work / ("job_" + self.canonical.job_uuid.replace("-", ""))).mkdir()
        with self.assertRaises(ArtifactUnavailable):
            open_job_report(self.canonical.job_uuid)
