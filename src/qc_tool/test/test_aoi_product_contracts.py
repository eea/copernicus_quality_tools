#!/usr/bin/env python3


import json
import re
from unittest import TestCase

from qc_tool.aoi import canonicalize_aoi_capture_groups
from qc_tool.aoi import extract_aoi_code_from_groups
from qc_tool.aoi import has_aoi_code_capture
from qc_tool.aoi import is_aoi_input_alias
from qc_tool.aoi import normalize_aoi_code
from qc_tool.common import QC_TOOL_PRODUCT_DIR


class TestAoiNormalization(TestCase):
    def test_product_and_boundary_aliases_resolve_to_aoi_code(self):
        aliases = (
            "aoi_code",
            "delivery_unit_id",
            "FUA_CODE",
            "fua",
            "DU_ID",
            "du",
            "CODE_CITY",
            "CodeCITY",
        )

        for alias in aliases:
            with self.subTest(alias=alias):
                self.assertTrue(is_aoi_input_alias(alias))
                self.assertEqual("EE003L1", extract_aoi_code_from_groups({alias: "EE003L1"}))

    def test_descriptive_and_generic_fields_are_not_aoi_aliases(self):
        for field_name in ("fua_name", "du_name", "country_code", "shortfua", "id"):
            with self.subTest(field_name=field_name):
                self.assertFalse(is_aoi_input_alias(field_name))

    def test_values_use_one_stable_identifier(self):
        expectations = {
            " EE003L1 ": "ee003l",
            "ee003l": "ee003l",
            "DU001A": "du001",
            "du001": "du001",
            "E73N22": "e73n22",
            "007": "007",
        }

        for raw_value, expected in expectations.items():
            with self.subTest(raw_value=raw_value):
                self.assertEqual(expected, normalize_aoi_code(raw_value))

    def test_conflicting_alias_values_are_rejected(self):
        with self.assertRaises(ValueError):
            extract_aoi_code_from_groups({"aoi_code": "mt", "delivery_unit_id": "du001a"})

    def test_equivalent_aliases_prefer_the_canonical_group(self):
        groups = {"aoi_code": "DU001", "delivery_unit_id": "DU001A"}

        self.assertEqual("DU001", extract_aoi_code_from_groups(groups))

    def test_input_aliases_do_not_leak_into_internal_groups(self):
        groups = canonicalize_aoi_capture_groups({
            "delivery_unit_id": "DU001A",
            "epsg_code": "3035",
        })

        self.assertEqual({"aoi_code": "DU001A", "epsg_code": "3035"}, groups)

    def test_descriptive_group_is_not_detected_as_aoi_code(self):
        self.assertFalse(has_aoi_code_capture(r"^(?P<fua_name>[a-z_]+)$"))


class TestAoiProductContracts(TestCase):
    def test_unchanged_n2k_definitions_publish_one_canonical_aoi_code(self):
        samples = {
            "n2k_2006.json": "N2K_DU001A_Status2006_LCLU_v1_20200915",
            "n2k_2012.json": "N2K_DU001A_Status2012_LCLU_v1_20200915",
            "n2k_2018.json": "N2K_DU001A_Status2018_LCLU_v1_20200915",
            "n2k_2012_change.json": "N2K_DU001A_Change2006_2012_LCLU_v1_20200915",
            "n2k_2018_change.json": "N2K_DU001A_Change2012_2018_LCLU_v1_20200915",
        }

        for product_filename, layer_name in samples.items():
            with self.subTest(product_filename=product_filename):
                product_definition = json.loads(
                    QC_TOOL_PRODUCT_DIR.joinpath(product_filename).read_text()
                )
                naming_step = next(
                    step for step in product_definition["steps"]
                    if step["check_ident"] == "qc_tool.vector.naming"
                )
                layer_regex = next(iter(naming_step["parameters"]["layer_names"].values()))
                match = re.match(layer_regex, layer_name, re.IGNORECASE)

                self.assertIsNotNone(match)
                raw_aoi_code = extract_aoi_code_from_groups(match.groupdict())
                self.assertEqual("DU001A", raw_aoi_code)
                self.assertEqual("du001", normalize_aoi_code(raw_aoi_code))
