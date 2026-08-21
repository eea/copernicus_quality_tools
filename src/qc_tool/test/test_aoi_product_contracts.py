#!/usr/bin/env python3


import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock
from unittest.mock import call
from unittest.mock import patch

from qc_tool.aoi import build_aoi_validation_plan
from qc_tool.aoi import canonicalize_aoi_capture_groups
from qc_tool.aoi import extract_aoi_code_from_groups
from qc_tool.aoi import has_aoi_code_capture
from qc_tool.aoi import is_aoi_input_alias
from qc_tool.aoi import mark_aoi_medium_not_applicable
from qc_tool.aoi import normalize_aoi_code
from qc_tool.aoi import product_uses_aoi
from qc_tool.aoi import validate_after_step
from qc_tool.aoi import validate_spatial_aoi_codes
from qc_tool.common import get_product_definitions
from qc_tool.common import load_product_definition
from qc_tool.common import QC_TOOL_PRODUCT_DIR
from qc_tool.worker.dispatch import CheckStatus


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
            "EE003Lx": "ee003l",
            "EE003Ly": "ee003l",
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

    def test_products_without_aoi_have_no_spatial_contract(self):
        product_definition = load_product_definition("general_raster")

        self.assertFalse(product_uses_aoi(product_definition))
        self.assertEqual(
            {
                "uses_aoi": False,
                "media": (),
                "contracts": {},
            },
            build_aoi_validation_plan(product_definition),
        )

    def test_ua_change_uses_product_scoped_vector_boundary(self):
        plan = build_aoi_validation_plan(
            load_product_definition("clms_ua_lcuc_c2021-2024_v010ha")
        )

        self.assertTrue(plan["uses_aoi"])
        self.assertEqual(("vector",), plan["media"])
        contract = plan["contracts"]["vector"]
        self.assertEqual("vector", contract["validator"])
        self.assertEqual(
            "boundary_ua2024_eea39_v1.gpkg",
            contract["source"],
        )
        self.assertEqual("fua_code", contract["code_field"])

    def test_coastal_zones_does_not_guess_aoi_from_unrelated_du_attribute(self):
        plan = build_aoi_validation_plan(load_product_definition("cz_2018"))

        self.assertIsNone(plan["contracts"]["vector"])

    def test_combined_product_has_independent_raster_and_vector_contracts(self):
        plan = build_aoi_validation_plan(
            load_product_definition("swf_2018_vec_ras")
        )

        self.assertEqual(("raster", "vector"), plan["media"])
        self.assertEqual("raster", plan["contracts"]["raster"]["validator"])
        self.assertEqual("vector", plan["contracts"]["vector"]["validator"])
        self.assertEqual("raster", plan["contracts"]["vector"]["source_type"])
        self.assertEqual(
            plan["contracts"]["raster"]["checks"],
            plan["contracts"]["vector"]["checks"],
        )

    def test_partial_raster_layer_mapping_fails_closed(self):
        product_definition = {
            "product_ident": "synthetic",
            "steps": [
                {
                    "check_ident": "qc_tool.raster.naming",
                    "parameters": {
                        "layer_names": {
                            "first": r"^(?P<aoi_code>[a-z]+)_first$",
                            "second": r"^(?P<aoi_code>[a-z]+)_second$",
                        },
                    },
                },
                {
                    "check_ident": "qc_tool.raster.gap",
                    "parameters": {
                        "layers": ["first"],
                        "mask": "default",
                    },
                },
            ],
        }

        plan = build_aoi_validation_plan(product_definition)

        self.assertTrue(plan["uses_aoi"])
        self.assertEqual(("raster",), plan["media"])
        self.assertIsNone(plan["contracts"]["raster"])

    def test_every_spatial_aoi_product_has_a_contract_or_is_explicitly_unsupported(self):
        unsupported_products = set()
        loaded_products = set()
        for product_ident in get_product_definitions():
            try:
                product_definition = load_product_definition(product_ident)
            except json.JSONDecodeError:
                # Canonical definitions are immutable and outside this
                # feature's scope. A malformed unrelated definition must not
                # prevent auditing every definition that the worker can load.
                continue
            loaded_products.add(product_ident)
            plan = build_aoi_validation_plan(product_definition)
            if plan["uses_aoi"] and any(
                plan["contracts"].get(medium) is None
                for medium in plan["media"]
            ):
                unsupported_products.add(product_ident)

        expected_unsupported_products = {
            "clms_euhydro_acc_ie_nir",
            "clms_euhydro_art_ie_nir",
            "clms_euhydro_bas_ie_nir",
            "clms_euhydro_coast_ie_nir",
            "clms_euhydro_dem_ie_nir",
            "clms_euhydro_dir_ie_nir",
            "clms_euhydro_net_ie_nir",
            "clms_euhydro_wbo_ie_nir",
            "cz_2012",
            "cz_2018",
            "cz_change_2012_2018",
        }
        self.assertEqual(
            expected_unsupported_products.intersection(loaded_products),
            unsupported_products,
        )

    def test_every_spatial_medium_has_one_required_validation_hook(self):
        hook_by_medium = {
            "raster": "qc_tool.raster.naming",
            "vector": "qc_tool.vector.import2pg",
        }
        for product_ident in get_product_definitions():
            try:
                product_definition = load_product_definition(product_ident)
            except json.JSONDecodeError:
                continue
            plan = build_aoi_validation_plan(product_definition)
            for medium in plan["media"]:
                with self.subTest(
                    product_ident=product_ident, medium=medium
                ):
                    hooks = [
                        step for step in product_definition["steps"]
                        if step["check_ident"] == hook_by_medium[medium]
                    ]
                    self.assertEqual(1, len(hooks))
                    self.assertTrue(hooks[0]["required"])


class TestSpatialAoiContract(TestCase):
    def test_matching_equivalent_codes_publish_one_canonical_value(self):
        status = CheckStatus()

        result = validate_spatial_aoi_codes(
            {"aoi_code": "EE003L1"},
            status,
            ["ee003l", "EE003L0"],
        )

        self.assertEqual("ee003l", result)
        self.assertEqual("ok", status.status)
        self.assertEqual("ee003l", status.status_properties["aoi_code"])
        self.assertEqual((), status.params["_aoi_validated_media"])

    def test_raster_and_vector_validation_accumulate_for_one_job_aoi(self):
        params = {
            "aoi_code": "EE003L1",
            "aoi_validation_plan": {
                "media": ("raster", "vector"),
            },
        }
        raster_status = CheckStatus()
        validate_spatial_aoi_codes(
            params, raster_status, ["ee003l"], medium="raster"
        )
        self.assertIsNone(raster_status.status_properties["aoi_code"])
        params.update(raster_status.params)

        vector_status = CheckStatus()
        validate_spatial_aoi_codes(
            params, vector_status, ["EE003L0"], medium="vector"
        )

        self.assertEqual("ee003l", vector_status.status_properties["aoi_code"])
        self.assertEqual(
            ("raster", "vector"),
            vector_status.params["_aoi_validated_media"],
        )

    def test_not_applicable_medium_cannot_replace_spatial_validation(self):
        status = CheckStatus()
        params = {
            "aoi_code": "mt",
            "aoi_validation_plan": {
                "media": ("vector",),
            },
        }

        result = mark_aoi_medium_not_applicable(
            params, status, medium="vector"
        )

        self.assertEqual("mt", result)
        self.assertEqual((), status.params["_aoi_validated_media"])
        self.assertEqual(
            ("vector",), status.params["_aoi_not_applicable_media"]
        )
        self.assertIsNone(status.status_properties["aoi_code"])

    def test_validation_replaces_not_applicable_state_for_same_medium(self):
        status = CheckStatus()
        params = {
            "aoi_code": "mt",
            "_aoi_not_applicable_media": ("vector",),
            "aoi_validation_plan": {
                "media": ("vector",),
            },
        }

        validate_spatial_aoi_codes(
            params, status, ["mt"], medium="vector"
        )

        self.assertEqual("mt", status.status_properties["aoi_code"])
        self.assertEqual(("vector",), status.params["_aoi_validated_media"])
        self.assertEqual((), status.params["_aoi_not_applicable_media"])

    def test_unknown_medium_cannot_complete_a_spatial_plan(self):
        status = CheckStatus()
        params = {
            "aoi_code": "mt",
            "_aoi_validated_media": ("unknown",),
            "_aoi_not_applicable_media": ("vector",),
            "aoi_validation_plan": {
                "media": ("vector",),
            },
        }

        validate_spatial_aoi_codes(
            params, status, ["mt"], medium="unknown"
        )

        self.assertIsNone(status.status_properties["aoi_code"])
        self.assertEqual((), status.params["_aoi_validated_media"])
        self.assertEqual(
            ("vector",), status.params["_aoi_not_applicable_media"]
        )

    def test_multiple_spatial_codes_abort_and_clear_the_job_aoi(self):
        status = CheckStatus()

        result = validate_spatial_aoi_codes(
            {"aoi_code": "mt"}, status, ["mt", "cz"]
        )

        self.assertIsNone(result)
        self.assertEqual("aborted", status.status)
        self.assertIsNone(status.params["aoi_code"])
        self.assertIsNone(status.status_properties["aoi_code"])
        self.assertTrue(status.params["_aoi_code_invalid"])
        self.assertEqual((), status.params["_aoi_validated_media"])

    def test_missing_job_aoi_is_a_no_op_for_aoi_less_products(self):
        status = CheckStatus()

        result = validate_spatial_aoi_codes({}, status, ["mt"])

        self.assertIsNone(result)
        self.assertEqual("ok", status.status)
        self.assertEqual({}, status.params)
        self.assertEqual({}, status.status_properties)

    @patch("qc_tool.vector.aoi.validate_aoi")
    def test_common_hook_delegates_to_the_vector_adapter(self, validate_aoi):
        status = CheckStatus()
        contract = {"validator": "vector"}
        params = {
            "aoi_code": "mt",
            "aoi_validation_plan": {
                "uses_aoi": True,
                "media": ("vector",),
                "contracts": {"vector": contract},
            },
        }

        validate_after_step("qc_tool.vector.import2pg", params, status)

        validate_aoi.assert_called_once_with(params, status, contract)

    @patch("qc_tool.vector.aoi.validate_aoi")
    def test_aborted_target_step_clears_unvalidated_aoi(self, validate_aoi):
        status = CheckStatus()
        status.aborted("Import failed.")
        status.add_params({
            "aoi_code": "mt",
            "_aoi_validated_media": ("raster",),
        })
        status.set_status_property("aoi_code", "mt")
        params = {
            "aoi_code": "mt",
            "aoi_validation_plan": {
                "uses_aoi": True,
                "media": ("raster", "vector"),
                "contracts": {"vector": {"validator": "vector"}},
            },
        }

        validate_after_step("qc_tool.vector.import2pg", params, status)

        validate_aoi.assert_not_called()
        self.assertEqual("aborted", status.status)
        self.assertIsNone(status.params["aoi_code"])
        self.assertEqual((), status.params["_aoi_validated_media"])
        self.assertEqual((), status.params["_aoi_not_applicable_media"])
        self.assertIsNone(status.status_properties["aoi_code"])

    @patch("qc_tool.vector.aoi.validate_aoi")
    @patch("qc_tool.raster.aoi.validate_aoi")
    def test_mixed_product_hook_delegates_to_both_adapters(
        self, validate_raster_aoi, validate_vector_aoi
    ):
        plan = build_aoi_validation_plan(
            load_product_definition("swf_2018_vec_ras")
        )
        params = {
            "aoi_code": "e50n22",
            "aoi_validation_plan": plan,
        }
        raster_status = CheckStatus()
        vector_status = CheckStatus()

        validate_after_step(
            "qc_tool.raster.naming", params, raster_status
        )
        validate_after_step(
            "qc_tool.vector.import2pg", params, vector_status
        )

        validate_raster_aoi.assert_called_once_with(
            params, raster_status, plan["contracts"]["raster"]
        )
        validate_vector_aoi.assert_called_once_with(
            params, vector_status, plan["contracts"]["vector"]
        )

    def test_missing_authoritative_mapping_fails_closed(self):
        status = CheckStatus()
        params = {
            "aoi_code": "ie_nir",
            "aoi_validation_plan": {
                "uses_aoi": True,
                "media": ("vector",),
                "contracts": {"vector": None},
                "product_ident": "clms_euhydro_art_ie_nir",
            },
        }

        validate_after_step("qc_tool.vector.import2pg", params, status)

        self.assertEqual("aborted", status.status)
        self.assertIsNone(status.params["aoi_code"])
        self.assertIn(
            "no authoritative vector boundary mapping", status.messages[0]
        )


class TestDispatchAoiLifecycle(TestCase):
    def test_spatial_hook_timeout_clears_aoi_and_cancels_alarm(self):
        from qc_tool.worker.dispatch import dispatch
        from qc_tool.worker.dispatch import TimedOutExc

        product_definition = {
            "product_ident": "test_raster_aoi",
            "steps": [
                {
                    "check_ident": "qc_tool.raster.naming",
                    "description": "Naming",
                    "required": True,
                    "parameters": {
                        "layer_names": {
                            "raster": r"^(?P<aoi_code>[a-z]+)$",
                        },
                    },
                },
                {
                    "check_ident": "qc_tool.raster.gap",
                    "description": "Coverage",
                    "required": False,
                    "parameters": {
                        "layers": ["raster"],
                        "mask": "test",
                    },
                },
            ],
        }

        def detect_aoi(params, status):
            from qc_tool.aoi import publish_aoi_code

            publish_aoi_code(params, status, "mt")

        def time_out_during_spatial_validation(params, status, contract):
            status.add_params({
                "aoi_code": "mt",
                "_aoi_validated_media": ("raster",),
            })
            status.set_status_property("aoi_code", "mt")
            raise TimedOutExc()

        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            delivery_path = temp_path.joinpath("delivery.zip")
            delivery_path.write_bytes(b"delivery")
            temp_path.joinpath("tmp").mkdir()
            temp_path.joinpath("output").mkdir()

            jobdir_manager = MagicMock()
            jobdir_manager.job_dir = temp_path
            jobdir_manager.tmp_dir = temp_path.joinpath("tmp")
            jobdir_manager.output_dir = temp_path.joinpath("output")
            jobdir_context = MagicMock()
            jobdir_context.__enter__.return_value = jobdir_manager
            connection_context = MagicMock()
            connection_context.__enter__.return_value = MagicMock()
            check_module = MagicMock()
            check_module.run_check.side_effect = detect_aoi

            with patch(
                "qc_tool.worker.dispatch.load_product_definition",
                return_value=product_definition,
            ), patch(
                "qc_tool.worker.dispatch.create_jobdir_manager",
                return_value=jobdir_context,
            ), patch(
                "qc_tool.worker.dispatch.create_connection_manager",
                return_value=connection_context,
            ), patch(
                "qc_tool.worker.dispatch.import_module",
                return_value=check_module,
            ), patch(
                "qc_tool.worker.dispatch.copy_product_definition_to_job"
            ), patch(
                "qc_tool.worker.dispatch.store_job_result"
            ), patch(
                "qc_tool.worker.dispatch.generate_pdf_report"
            ), patch(
                "qc_tool.worker.dispatch.get_qc_tool_version",
                return_value="test",
            ), patch(
                "qc_tool.worker.dispatch.get_timeout",
                return_value={"hours": 0, "minutes": 0, "seconds": 5},
            ), patch(
                "qc_tool.worker.dispatch.signal"
            ), patch(
                "qc_tool.worker.dispatch.alarm"
            ) as alarm, patch(
                "qc_tool.raster.aoi.validate_aoi",
                side_effect=time_out_during_spatial_validation,
            ):
                result = dispatch(
                    "00000000-0000-0000-0000-000000000001",
                    "test-user",
                    delivery_path,
                    "test_raster_aoi",
                )

        self.assertIsNone(result["aoi_code"])
        self.assertEqual("failed", result["status"])
        self.assertEqual("aborted", result["steps"][0]["status"])
        self.assertEqual([call(5), call(0)], alarm.call_args_list)
