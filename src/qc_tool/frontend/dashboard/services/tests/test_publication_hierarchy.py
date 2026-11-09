"""Explicit publication versions retain legacy evidence and canonical run trees."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from qc_tool.jobs import create_job_paths, record_job_context
from qc_tool.frontend.dashboard.services.submissions.errors import PublicationError
from qc_tool.frontend.dashboard.services.submissions.publication import publish_reserved_submission
from qc_tool.frontend.dashboard.services.submissions.publication.layout import publication_layout
from qc_tool.frontend.dashboard.services.submissions.publication.manifest import receipt_from_existing
from .test_product_unit_boundaries import PublicationVersionTests


class PublicationHierarchyTests(PublicationVersionTests):
    def test_new_path_identifies_product_set_revision_definition_and_opaque_unit(self):
        layout = publication_layout(self.reserved, submission_root=self.root)
        self.assertEqual(layout.final_directory.relative_to(self.root).parts, (
            "product-4-sample", "specification-2-2026-r1-" + "d" * 64,
            "product-unit-3-007", "submission-{}.d".format(self.reserved.submission_uuid),
        ))
        for changed in (replace(self.reserved, release_revision=2), replace(self.reserved, definition_digest="e" * 64)):
            self.assertNotEqual(publication_layout(changed, submission_root=self.root).final_directory, layout.final_directory)

    def test_missing_or_invalid_explicit_identity_cannot_create_a_new_publication(self):
        for changes in ({"product_id": None}, {"product_ident": ""}, {"release_revision": None},
                        {"release_revision": True}, {"definition_digest": "unknown"}, {"release_key": "///"}):
            with self.subTest(changes=changes), self.assertRaises(PublicationError) as error:
                publication_layout(replace(self.reserved, **changes), submission_root=self.root)
            self.assertEqual(error.exception.code, "publication_identity_unavailable")

    def test_current_legacy_path_recovers_even_when_new_identity_is_unavailable(self):
        current, payload, digest = self.write_publication(2)
        old = self.root / "release-2-2026" / "product-unit-3-007" / current.name
        old.parent.mkdir(parents=True)
        current.rename(old)
        reserved = replace(self.reserved, product_id=None, definition_digest="")
        for candidate in (reserved, replace(reserved, artifact_key=old.relative_to(self.root).as_posix())):
            layout = publication_layout(candidate, submission_root=self.root)
            self.assertEqual(layout.final_directory, old)
            self.assertEqual(receipt_from_existing(old, candidate, submission_root=self.root).artifact_digest, digest)
        self.assertEqual((old / "submission-manifest.json").read_bytes(), payload)

    def test_canonical_job_publication_preserves_nested_identity_and_excludes_diagnostics(self):
        incoming = self.root / "incoming" / self.reserved.username
        incoming.mkdir(parents=True)
        (incoming / self.reserved.filename).write_bytes(self.input_bytes)
        paths = create_job_paths(self.root / "jobs", self.reserved.job_uuid)
        specification = b'{"original": "specification bytes"}'
        reserved = replace(self.reserved, definition_digest=hashlib.sha256(specification).hexdigest())
        paths.specification_path("result.json").write_bytes(specification)
        paths.result_path.write_text('{"status":"ok"}')
        paths.report_path("report.pdf").write_bytes(b"retained report")
        (paths.output_dir / "error.gpkg").write_bytes(b"retained check attachment")
        paths.worker_log_path.write_bytes(b"private worker diagnostic")
        paths.console_log_path.write_bytes(b"private console diagnostic")
        record_job_context(paths, specification_filename="result.json", specification_sha256=hashlib.sha256(specification).hexdigest())
        with patch("qc_tool.frontend.dashboard.services.submissions.publication.compose_job_dir", return_value=paths.directory):
            receipt = publish_reserved_submission(reserved, submission_root=self.root / "published", media_root=self.root / "incoming")
        final = self.root / "published" / receipt.artifact_key
        manifest = json.loads((final / "submission-manifest.json").read_bytes())
        self.assertEqual({item["path"] for item in manifest["files"]}, {
            "job.json", "result.json", "specification/result.json", "reports/report.pdf",
            "outputs/error.gpkg", "input.d/unit.zip", "SUBMITTED",
        })
        self.assertEqual((final / "specification/result.json").read_bytes(), specification)
        self.assertFalse((final / "logs").exists())
        self.assertEqual(receipt_from_existing(final, reserved, submission_root=self.root / "published").artifact_digest, receipt.artifact_digest)

    def test_canonical_publication_refuses_specification_drift_before_exposure(self):
        incoming = self.root / "incoming" / self.reserved.username
        incoming.mkdir(parents=True)
        (incoming / self.reserved.filename).write_bytes(self.input_bytes)
        paths = create_job_paths(self.root / "jobs", self.reserved.job_uuid)
        specification = b'{"original": "specification bytes"}'
        digest = hashlib.sha256(specification).hexdigest()
        paths.specification_path("job.json").write_bytes(specification)
        paths.result_path.write_text('{"status":"ok"}')
        record_job_context(paths, specification_filename="job.json", specification_sha256=digest)
        changed_file = replace(self.reserved, definition_digest=digest)
        with patch("qc_tool.frontend.dashboard.services.submissions.publication.compose_job_dir", return_value=paths.directory):
            for reserved in (self.reserved, changed_file):
                if reserved == changed_file:
                    paths.specification_path("job.json").write_bytes(b"changed bytes")
                with self.subTest(catalog_digest=reserved.definition_digest), self.assertRaises(PublicationError) as error:
                    publish_reserved_submission(reserved, submission_root=self.root / "published", media_root=self.root / "incoming")
                self.assertEqual(error.exception.code, "job_specification_mismatch")
                self.assertFalse(publication_layout(reserved, submission_root=self.root / "published").final_directory.exists())

    def test_symlink_product_parent_cannot_publish_outside_the_root(self):
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        (self.root / "product-4-sample").symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaises(PublicationError):
            publication_layout(self.reserved, submission_root=self.root)
        self.assertEqual(list(elsewhere.iterdir()), [])
