from pathlib import Path
from unittest import TestCase

from qc_tool.aoi import AOI_INPUT_ALIASES
from qc_tool.vector.helper import LayerDefsBuilder
from qc_tool.vector.helper import check_gdb_filename
from qc_tool.worker.aoi import merge_step_aoi_metadata
from qc_tool.worker.status import CheckStatus


class WorkerAoiMetadataTests(TestCase):
    def test_layer_builder_preserves_every_alias_and_publishes_aoi(self):
        for alias in AOI_INPUT_ALIASES:
            with self.subTest(alias=alias):
                status = CheckStatus()
                builder = LayerDefsBuilder(status)
                builder.add_layer_info(None, "UA_EE003L1_DATA")

                builder.extract_layer_def(
                    r"^UA_(?P<{}>[A-Z0-9]+)_DATA$".format(alias),
                    "delivery",
                )

                groups = builder.layer_defs["delivery"]["groups"]
                self.assertEqual(groups[alias], "EE003L1")
                self.assertEqual(groups["aoi_code"], "EE003L1")
                self.assertEqual(
                    status.status_properties["aoi_code"],
                    "ee003l",
                )

    def test_conflicting_layer_aliases_clear_metadata(self):
        status = CheckStatus()
        builder = LayerDefsBuilder(status)
        builder.add_layer_info(None, "EE003L1-EE004L")

        builder.extract_layer_def(
            r"^(?P<aoi_code>[A-Z0-9]+)-(?P<fua_code>[A-Z0-9]+)$",
            "delivery",
        )

        self.assertTrue(status.is_aborted())
        self.assertNotIn("delivery", builder.layer_defs)
        self.assertIsNone(status.status_properties["aoi_code"])

    def test_later_required_layer_failure_cannot_leave_stale_aoi(self):
        status = CheckStatus()
        builder = LayerDefsBuilder(status)
        builder.add_layer_info(None, "UA_EE003L1_DATA")
        builder.extract_layer_def(
            r"^UA_(?P<fua_code>[A-Z0-9]+)_DATA$",
            "present",
        )

        builder.extract_layer_def(
            r"^MISSING_(?P<fua_code>[A-Z0-9]+)$",
            "missing",
        )

        self.assertTrue(status.is_aborted())
        self.assertIsNone(status.status_properties["aoi_code"])

    def test_invalid_geodatabase_name_clears_previously_published_aoi(self):
        status = CheckStatus()
        status.set_status_property("FUA-Code", "EE003L1")

        check_gdb_filename(
            Path("wrong.gdb"),
            r"^UA_(?P<fua_code>[A-Z0-9]+)\.gdb$",
            "EE003L1",
            status,
        )

        self.assertTrue(status.is_aborted())
        self.assertIsNone(status.status_properties["aoi_code"])

    def test_external_alias_is_published_under_only_canonical_key(self):
        status = CheckStatus()

        status.set_status_property("fua_code", "EE003L1")
        merge_step_aoi_metadata({}, status)

        self.assertEqual(status.status_properties, {"aoi_code": "ee003l"})
        self.assertEqual(status.params["aoi_code"], "ee003l")
        self.assertNotIn("fua_code", status.status_properties)

    def test_canonical_result_preserves_equivalent_raw_downstream_parameter(self):
        status = CheckStatus()
        status.add_params({"aoi_code": "007"})
        status.set_status_property("aoi_code", "007")

        merge_step_aoi_metadata({}, status)

        self.assertEqual(status.status_properties["aoi_code"], "7")
        self.assertEqual(status.params["aoi_code"], "007")

    def test_later_equivalent_step_keeps_the_first_raw_parameter(self):
        job_params = {}
        first = CheckStatus()
        first.add_params({"aoi_code": "007"})
        first.set_status_property("aoi_code", "007")
        merge_step_aoi_metadata(job_params, first)
        job_params.update(first.status_properties)
        job_params.update(first.params)

        second = CheckStatus()
        second.set_status_property("aoi_code", "7")
        merge_step_aoi_metadata(job_params, second)

        self.assertEqual(second.status_properties["aoi_code"], "7")
        self.assertEqual(second.params["aoi_code"], "007")

    def test_conflicting_steps_clear_metadata_without_changing_qc_status(self):
        first = CheckStatus()
        first.set_status_property("delivery_unit_id", "DU001A")
        job_params = {}
        merge_step_aoi_metadata(job_params, first)
        job_params.update(first.status_properties)
        job_params.update(first.params)

        second = CheckStatus()
        second.set_status_property("du_id", "DU002")
        merge_step_aoi_metadata(job_params, second)

        self.assertEqual(second.status, "ok")
        self.assertIsNone(second.status_properties["aoi_code"])
        self.assertTrue(second.params["_aoi_code_conflict"])
        self.assertIn("conflicting identifiers", second.messages[0])
