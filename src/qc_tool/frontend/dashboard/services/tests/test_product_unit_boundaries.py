"""Versioned input contracts preserve opaque units and legacy evidence."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from uuid import uuid4

from django.test import SimpleTestCase

from qc_tool.common import JOB_INPUT_DIRNAME, JOB_OUTPUT_DIRNAME
from qc_tool.product_units import normalize_product_unit_code
from qc_tool.frontend.dashboard.services.product_units.results import product_unit_update_from_result
from qc_tool.frontend.dashboard.services.product_units.contracts import ProductUnitUpdateAction
from qc_tool.frontend.dashboard.services.catalog.errors import CatalogError
from qc_tool.frontend.dashboard.services.catalog.manifest.coverage import extract_definition_product_units, extract_coverage_product_units
from qc_tool.frontend.dashboard.services.submissions.contracts import ReservedSubmission
from qc_tool.frontend.dashboard.services.submissions.errors import PublicationError
from qc_tool.frontend.dashboard.services.submissions.publication.layout import publication_layout
from qc_tool.frontend.dashboard.services.submissions.publication.manifest import build_manifest, receipt_from_existing


class ProductUnitInputTests(SimpleTestCase):
    def test_opaque_units_preserve_suffixes_and_padding(self):
        for raw, expected in ((" EE001L1 ", "ee001l1"), ("007", "007"), ("Sheet-09-X", "sheet-09-x")):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_product_unit_code(raw), expected)
                update = product_unit_update_from_result({"product_unit_code": raw})
                self.assertEqual(update.value, expected)
                self.assertIs(update.action, ProductUnitUpdateAction.SET)
        self.assertEqual(product_unit_update_from_result({"aoi_code": "EE001L1"}).value, "ee001l")
        self.assertEqual(product_unit_update_from_result({"aoi_code": "007"}).value, "7")

    def test_absence_and_malformed_preserve_null_clears(self):
        for document in (None, [], {}, {"product_unit_code": 7}, {"product_unit_code": ""}, {"product_unit_code": "a\x00b"}):
            with self.subTest(document=document):
                self.assertIs(product_unit_update_from_result(document).action, ProductUnitUpdateAction.PRESERVE)
        for key in ("product_unit_code", "aoi_code"):
            self.assertIs(product_unit_update_from_result({key: None}).action, ProductUnitUpdateAction.CLEAR)

    def test_alias_conflicts_preserve_the_projection_and_input(self):
        for document in (
            {"product_unit_code": "007", "aoi_code": "007"},
            {"product_unit_code": "ee001l1", "aoi_code": "EE001L1"},
            {"product_unit_code": "tile-07", "aoi_code": None},
        ):
            original = dict(document)
            update = product_unit_update_from_result(document)
            self.assertIs(update.action, ProductUnitUpdateAction.PRESERVE)
            self.assertTrue(update.conflicted)
            self.assertEqual(document, original)
        self.assertEqual(product_unit_update_from_result({"product_unit_code": "ee001l", "aoi_code": "EE001L1"}).value, "ee001l")

    def test_explicit_definition_units_are_opaque_and_keep_sources(self):
        document = {"product_units": ["007", "EE001L1", "Sheet-09-X"], "steps": []}
        self.assertEqual(extract_definition_product_units(document), {"007": "007", "ee001l1": "EE001L1", "sheet-09-x": "Sheet-09-X"})
        definition = SimpleNamespace(product_ident="sample", document=document)
        codes, sources, provenance = extract_coverage_product_units({"source_definition": "sample"}, [definition], state="draft")
        self.assertEqual(codes, ["007", "ee001l1", "sheet-09-x"])
        self.assertEqual(sources, ["007", "EE001L1", "Sheet-09-X"])
        self.assertEqual(provenance, "definition")

    def test_explicit_units_cannot_contradict_finite_executable_naming(self):
        document = {"product_units": ["EE001L1"], "steps": [{"check_ident": "qc_tool.vector.naming", "parameters": {"aoi_codes": ["EE001L1"]}}]}
        with self.assertRaises(CatalogError):
            extract_definition_product_units(document)
        document["product_units"] = ["ee001l"]
        self.assertEqual(extract_definition_product_units(document), {"ee001l": "ee001l"})

    def test_real_bundled_legacy_definition_retains_naming_contract(self):
        root = next(parent for parent in Path(__file__).resolve().parents if (parent / "product_definitions").is_dir())
        document = json.loads((root / "product_definitions" / "rpz_2012.json").read_text())
        before = json.dumps(document, sort_keys=True)
        units = extract_definition_product_units(document)
        self.assertTrue(units)
        self.assertEqual(json.dumps(document, sort_keys=True), before)
        naming = [step for step in document["steps"] if step["check_ident"].endswith(".naming")]
        self.assertTrue(any("aoi_codes" in step["parameters"] for step in naming))
        self.assertIn("du001", units)
        self.assertEqual(units["du001"], "du001")


class PublicationVersionTests(SimpleTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.input_bytes = b"retained input"
        self.reserved = ReservedSubmission(
            submission_uuid=uuid4(), delivery_id=1, job_uuid=uuid4(),
            product_release_id=2, product_unit_id=3, release_key="2026",
            product_unit_code="007", submitted_product_unit_code="007",
            username="owner", filename="unit.zip", is_s3=False,
            expected_input_digest=hashlib.sha256(self.input_bytes).hexdigest(),
            requested_at_iso="2026-01-01T00:00:00Z", already_existed=False,
        )

    def write_publication(self, version):
        layout = publication_layout(self.reserved, submission_root=self.root)
        final = layout.final_directory
        final.mkdir()
        (final / JOB_INPUT_DIRNAME).mkdir()
        (final / JOB_OUTPUT_DIRNAME).mkdir()
        inventory = []
        for path, payload in ((JOB_INPUT_DIRNAME + "/unit.zip", self.input_bytes), ("SUBMITTED", b"")):
            (final / path).write_bytes(payload)
            inventory.append({"path": path, "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
        payload, digest = build_manifest(self.reserved, input_digest=self.reserved.expected_input_digest, file_inventory=inventory)
        if version == 1:
            body = json.loads(payload)
            body.pop("artifact_sha256")
            body["schema_version"] = 1
            for new, old in (("product_unit_id", "product_aoi_id"), ("product_unit_code", "aoi_code"), ("submitted_product_unit_code", "aoi_code_submitted")):
                body[old] = body.pop(new)
            canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            digest = hashlib.sha256(canonical).hexdigest()
            payload = json.dumps({**body, "artifact_sha256": digest}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        (final / "submission-manifest.json").write_bytes(payload)
        return final, payload, digest

    def test_new_publication_uses_version_two_and_product_unit_path(self):
        final, payload, digest = self.write_publication(2)
        self.assertTrue(final.parent.name.startswith("product-unit-"))
        self.assertEqual(json.loads(payload)["schema_version"], 2)
        self.assertEqual(receipt_from_existing(final, self.reserved).artifact_digest, digest)

    def test_old_publication_recovery_keeps_original_bytes_checksum_and_path(self):
        current, payload, digest = self.write_publication(1)
        old_parent = current.parent.with_name("aoi-3-007")
        old_parent.mkdir()
        legacy = old_parent / current.name
        current.rename(legacy)
        for reserved in (self.reserved, replace(self.reserved, artifact_path=str(legacy))):
            layout = publication_layout(reserved, submission_root=self.root)
            self.assertEqual(layout.final_directory, legacy)
            self.assertEqual(receipt_from_existing(legacy, reserved).artifact_digest, digest)
        self.assertEqual((legacy / "submission-manifest.json").read_bytes(), payload)

    def test_legacy_manifest_rejects_new_aliases_even_with_valid_checksum(self):
        final, payload, _digest = self.write_publication(1)
        body = json.loads(payload)
        body.pop("artifact_sha256")
        body["product_unit_code"] = "007"
        canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        body["artifact_sha256"] = hashlib.sha256(canonical).hexdigest()
        (final / "submission-manifest.json").write_text(json.dumps(body))
        with self.assertRaises(PublicationError):
            receipt_from_existing(final, self.reserved)
