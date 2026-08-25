from unittest import TestCase

from qc_tool.aoi import aoi_codes_equivalent
from qc_tool.aoi import canonicalize_aoi_capture_groups
from qc_tool.aoi import extract_aoi_code_from_groups
from qc_tool.aoi import has_aoi_code_capture
from qc_tool.aoi import merge_aoi_metadata
from qc_tool.aoi import normalize_aoi_code
from qc_tool.aoi import with_canonical_aoi_capture


class AoiIdentifierTests(TestCase):
    def test_normalizes_legacy_fua_and_delivery_unit_suffixes(self):
        cases = {
            " EE003L1 ": "ee003l",
            "EE003LX": "ee003l",
            "ee003ly": "ee003l",
            "DU001A": "du001",
            "007": "7",
            "custom-AOI": "custom-aoi",
        }

        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(normalize_aoi_code(source), expected)

    def test_rejects_empty_non_string_and_oversized_values(self):
        for value in (
            None,
            b"AOI",
            "  ",
            "AOI\nCODE",
            "AOI\u202eCODE",
            "x" * 256,
        ):
            with self.subTest(value=value):
                self.assertIsNone(normalize_aoi_code(value))

    def test_accepts_aliases_case_and_separator_insensitively(self):
        groups = {
            "FUA-Code": "EE003L1",
            "delivery_unit_id": "ee003l",
            "epsg_code": "3035",
        }

        self.assertEqual(
            normalize_aoi_code(extract_aoi_code_from_groups(groups)),
            "ee003l",
        )
        self.assertTrue(has_aoi_code_capture(r"(?P<fua_code>[A-Z0-9]+)"))

    def test_conflicting_alias_values_fail_closed(self):
        with self.assertRaises(ValueError):
            extract_aoi_code_from_groups(
                {"aoi_code": "ee003l", "fua_code": "ee004l"}
            )

    def test_internal_groups_can_preserve_aliases_or_publish_only_canonical_key(self):
        groups = {"fua_code": "EE003L1", "fua_name": "Example"}

        internal = with_canonical_aoi_capture(groups)
        public = canonicalize_aoi_capture_groups(groups)

        self.assertEqual(internal["fua_code"], "EE003L1")
        self.assertEqual(internal["aoi_code"], "EE003L1")
        self.assertNotIn("fua_code", public)
        self.assertEqual(public["aoi_code"], "ee003l")
        self.assertEqual(public["fua_name"], "Example")

    def test_equivalence_supports_established_product_representations(self):
        self.assertTrue(aoi_codes_equivalent("EE003L1", "ee003l"))
        self.assertTrue(aoi_codes_equivalent("DU001A", "du001"))
        self.assertTrue(aoi_codes_equivalent("007", "7"))
        self.assertFalse(aoi_codes_equivalent("ee003l", "ee004l"))


class AoiMetadataMergeTests(TestCase):
    def test_merges_equivalent_values_to_one_canonical_value(self):
        merged = merge_aoi_metadata("EE003L1", "ee003lx")

        self.assertEqual(merged.value, "ee003l")
        self.assertFalse(merged.conflicted)

    def test_conflict_remains_fail_closed_for_later_steps(self):
        conflicted = merge_aoi_metadata("ee003l", "ee004l")
        later = merge_aoi_metadata(
            conflicted.value,
            "ee003l",
            already_conflicted=conflicted.conflicted,
        )

        self.assertIsNone(conflicted.value)
        self.assertTrue(conflicted.conflicted)
        self.assertIsNone(later.value)
        self.assertTrue(later.conflicted)
