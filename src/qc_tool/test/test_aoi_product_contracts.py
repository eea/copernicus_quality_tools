#!/usr/bin/env python3


import json
from unittest import TestCase

from qc_tool.common import QC_TOOL_PRODUCT_DIR


def _produces_aoi_code(parameters):
    if parameters.get("aoi_codes"):
        return True

    return any(
        "(?P<aoi_code>" in layer_regex
        for layer_regex in parameters.get("layer_names", {}).values()
    )


class TestAoiProductContracts(TestCase):
    def test_fixed_vector_aoi_boundaries_declare_code_field(self):
        fixed_boundary_contracts = []
        missing_code_fields = []

        for product_filepath in sorted(QC_TOOL_PRODUCT_DIR.glob("*.json")):
            product_definition = json.loads(product_filepath.read_text())
            for step_number, step_definition in enumerate(product_definition.get("steps", []), start=1):
                if step_definition.get("check_ident") != "qc_tool.vector.naming":
                    continue

                parameters = step_definition.get("parameters", {})
                boundary_source = parameters.get("boundary_source")
                if not boundary_source or not _produces_aoi_code(parameters):
                    continue
                if "{" in boundary_source:
                    # AOI-specific boundary paths are resolved from the
                    # already detected code and do not expose a code field.
                    continue

                contract_location = "{:s}: step {:d}".format(product_filepath.name, step_number)
                fixed_boundary_contracts.append(contract_location)
                if not parameters.get("aoi_boundary_code_field"):
                    missing_code_fields.append(contract_location)

        self.assertTrue(fixed_boundary_contracts)
        self.assertEqual(
            [],
            missing_code_fields,
            "Fixed AOI boundary sources must declare aoi_boundary_code_field: {:s}".format(
                ", ".join(missing_code_fields)
            ),
        )
