"""Recognize reviewed delivery conventions without catalog or unit side effects."""

from dataclasses import FrozenInstanceError
import sys
from unittest import TestCase
from unittest.mock import patch

from qc_tool.delivery_names import (
    DeliveryNameParserUnavailable,
    _describe_schema,
    describe_delivery_schema,
    parse_delivery_name,
)


VERVIERS = "CLMS_UA_LCUC_C2021-2024_V010ha_BE015L1_VERVIERS_03035_V01_R00_20260730.zip"


class DeliveryNameTests(TestCase):
    def test_exact_verviers_delivery_has_expected_identity_and_raw_unit_hint(self):
        result = parse_delivery_name(VERVIERS)
        self.assertEqual(result.status, "recognized")
        self.assertEqual(result.filename, VERVIERS)
        self.assertEqual(result.family, "copernicus:clms:ua-lcu")
        self.assertEqual(result.schema_version, "0.0.0")
        self.assertEqual(result.fields["product"], "UA")
        self.assertEqual(result.fields["variable"], "LCUC")
        self.assertEqual(result.fields["survey"], "C2021-2024")
        self.assertEqual(result.fields["type"], "V")
        self.assertEqual(result.fields["resolution"], "010ha")
        self.assertEqual(result.fields["area_code"], "BE015L1")
        self.assertEqual(result.fields["epsg_code"], "03035")
        self.assertEqual(result.fields["production_date"], "20260730")
        self.assertNotIn("submitted_product_unit_code", result.fields)
        self.assertNotIn("product_ident", result.fields)

    def test_schema_tokens_are_canonical_but_raw_basename_and_area_are_preserved(self):
        name = VERVIERS.lower().replace("010ha", "010HA")
        result = parse_delivery_name(name)
        self.assertEqual(result.status, "recognized")
        self.assertEqual(result.filename, name)
        self.assertEqual(result.fields["variable"], "LCUC")
        self.assertEqual(result.fields["survey"], "C2021-2024")
        self.assertEqual(result.fields["resolution"], "010ha")
        self.assertEqual(result.fields["area_code"], "be015l1")
        self.assertEqual(result.fields["representation"], "vector")

    def test_representation_is_consistent_for_lowercase_raster_and_tree_tokens(self):
        examples = (
            ("CLMS_UA_BBH_S2021_R10m_DK004L3_AALBORG_03035_V01_R00_20240212.zip", "raster"),
            ("CLMS_UA_STL_S2021_VEC_AT001L3_WIEN_03035_V01_R01_20251030.gpkg.zip", "vector"),
        )
        for filename, expected in examples:
            with self.subTest(filename=filename):
                result = parse_delivery_name(filename.lower())
                self.assertEqual(result.status, "recognized")
                self.assertEqual(result.fields["representation"], expected)

    def test_outer_zip_is_an_archive_wrapper_not_the_inner_extension(self):
        name = VERVIERS[:-4] + ".gpkg.ZIP"
        result = parse_delivery_name(name)
        self.assertEqual(result.status, "recognized")
        self.assertEqual(result.filename, name)
        self.assertEqual(result.fields["extension"], "gpkg")
        self.assertNotIn("extension", parse_delivery_name(VERVIERS).fields)

    def test_copy_suffix_is_invalid_and_never_removed(self):
        name = VERVIERS[:-4] + " (1).zip"
        result = parse_delivery_name(name)
        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.filename, name)
        self.assertEqual(result.fields, {})
        self.assertEqual(result.message, "The filename contains a copy suffix such as (1). Use the original delivery filename and upload it again.")

    def test_copy_suffix_guidance_applies_to_explicitly_configured_names_only(self):
        name = "U2006_CLC2000_V2018_20b2 (1).zip"
        self.assertEqual(parse_delivery_name(name).status, "unsupported")
        result = parse_delivery_name(name, family="copernicus:clms:clc", schema_version="1.1.0")
        self.assertEqual(result.status, "invalid")
        self.assertIn("copy suffix", result.message)
        self.assertEqual(result.filename, name)

    def test_legacy_or_unrelated_names_remain_unsupported(self):
        for name in ("be015l_verviers_ua2012.zip", "generic-delivery.zip", "landsat-file.zip"):
            with self.subTest(name=name):
                self.assertEqual(parse_delivery_name(name).status, "unsupported")

    def test_malformed_recognized_urban_atlas_names_are_invalid(self):
        for name in ("CLMS_UA_.zip", "CLMS_UA_UNKNOWN_S2021.zip", VERVIERS.replace("BE015L1", "BAD")):
            with self.subTest(name=name):
                self.assertEqual(parse_delivery_name(name).status, "invalid")

    def test_existing_urban_atlas_pdf_recipe_remains_available_to_legacy_resolution(self):
        name = "CLMS_UA_PDF_S2024_V025ha_BE015L1_VERVIERS_03035_V01_R00_20260730.zip"
        for filename in (name, name.lower()):
            with self.subTest(filename=filename):
                result = parse_delivery_name(filename)
                self.assertEqual(result.status, "unsupported")
                self.assertEqual(result.fields, {})
                self.assertIsNone(result.family)

    def test_street_tree_schema_is_selected_independently(self):
        result = parse_delivery_name("CLMS_UA_STL_S2021_VEC_AT001L3_WIEN_03035_V01_R01_20251030.gpkg.zip")
        self.assertEqual(result.status, "recognized")
        self.assertEqual(result.family, "copernicus:clms:ua-stl")
        self.assertEqual(result.fields["type"], "VEC")
        self.assertNotIn("resolution", result.fields)

    def test_dhm_uses_its_own_pinned_schema_and_preserves_unicode_city(self):
        result = parse_delivery_name("DE074Lx_GÖRLITZ_UA2021_DHM.shp.zip")
        self.assertEqual(result.status, "recognized")
        self.assertEqual(result.family, "copernicus:clms:ua-dhm")
        self.assertEqual(result.fields["city"], "GÖRLITZ")
        self.assertEqual(result.fields["area_code"], "DE074Lx")
        self.assertEqual(result.fields["reference_year"], "2021")

    def test_bbh_and_gua_use_lcu_schema_without_erasing_the_variable(self):
        for variable in ("BBH", "GUA"):
            result = parse_delivery_name(VERVIERS.replace("LCUC_C2021-2024", variable + "_S2024"))
            self.assertEqual(result.status, "recognized")
            self.assertEqual(result.fields["variable"], variable)

    def test_production_date_must_exist_in_calendar(self):
        for invalid in ("20260230", "20261301", "00000101", "20230229"):
            with self.subTest(value=invalid):
                result = parse_delivery_name(VERVIERS.replace("20260730", invalid))
                self.assertEqual(result.status, "invalid")
                self.assertIn("valid calendar date", result.message)
        self.assertEqual(parse_delivery_name(VERVIERS.replace("20260730", "20240229")).status, "recognized")

    def test_change_survey_must_be_chronological(self):
        for invalid in ("C2024-2021", "C2024-2024", "C0000-2024"):
            with self.subTest(value=invalid):
                result = parse_delivery_name(VERVIERS.replace("C2021-2024", invalid))
                self.assertEqual(result.status, "invalid")
                self.assertIn("survey period", result.message)

    def test_status_survey_cannot_use_year_zero(self):
        result = parse_delivery_name(VERVIERS.replace("LCUC_C2021-2024", "LCU_S0000"))
        self.assertEqual(result.status, "invalid")
        self.assertIn("survey year", result.message)

    def test_explicit_other_family_requires_a_real_packaged_schema_version(self):
        name = "U2006_CLC2000_V2018_20b2.zip"
        self.assertEqual(parse_delivery_name(name).status, "unsupported")
        result = parse_delivery_name(name, family="copernicus:clms:clc", schema_version="1.1.0")
        self.assertEqual(result.status, "recognized")
        self.assertEqual(result.fields["product"], "CLC")
        self.assertEqual(result.schema_version, "1.1.0")
        self.assertEqual(parse_delivery_name(name, family="clc", schema_version="99.0.0").status, "invalid")

    def test_partial_or_path_schema_configuration_is_rejected(self):
        for config in (
            {"family": "ua-lcu"}, {"schema_version": "0.0.0"},
            {"family": "../../ua-lcu", "schema_version": "0.0.0"},
            {"family": "https://example.test/schema", "schema_version": "0.0.0"},
            {"family": "fabricated:namespace:ua-lcu", "schema_version": "0.0.0"},
        ):
            with self.subTest(config=config):
                self.assertEqual(parse_delivery_name(VERVIERS, **config).status, "invalid")

    def test_basename_limits_reject_paths_controls_and_invalid_unicode(self):
        for name in (None, "", "..", "../" + VERVIERS, "C:\\" + VERVIERS, "x/" + VERVIERS, "x\x00.zip", "x\ud800.zip", "x\u202e.zip", "é" * 126 + ".zip"):
            with self.subTest(name=repr(name)):
                self.assertEqual(parse_delivery_name(name).status, "invalid")
        self.assertEqual(parse_delivery_name("x" * 251 + ".zip").status, "unsupported")

    def test_schema_description_exposes_fields_as_independent_metadata(self):
        first = describe_delivery_schema("ua-lcu", "0.0.0")
        self.assertEqual(first["schema_id"], "copernicus:clms:ua-lcu")
        self.assertIn("LCUC", first["fields"]["variable"]["enum"])
        self.assertIn("pattern", first["fields"]["resolution"])
        first["fields"]["variable"]["enum"].clear()
        second = describe_delivery_schema("ua-lcu", "0.0.0")
        self.assertIn("LCUC", second["fields"]["variable"]["enum"])

    def test_missing_dependency_fails_explicitly(self):
        _describe_schema.cache_clear()
        self.addCleanup(_describe_schema.cache_clear)
        with patch.dict(sys.modules, {"parseo": None, "parseo.parser": None}):
            with self.assertRaises(DeliveryNameParserUnavailable):
                parse_delivery_name(VERVIERS)

    def test_observations_are_frozen_and_fields_are_not_shared(self):
        result = parse_delivery_name(VERVIERS)
        with self.assertRaises(FrozenInstanceError):
            result.status = "unsupported"
        result.fields["area_code"] = "changed"
        self.assertEqual(parse_delivery_name(VERVIERS).fields["area_code"], "BE015L1")
