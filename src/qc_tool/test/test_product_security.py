from unittest import TestCase

from qc_tool.product_security import UnsafeProductDefinition
from qc_tool.product_security import validate_executable_product_configuration


def enum_definition(value):
    return {
        "steps": [
            {
                "check_ident": "qc_tool.vector.enum",
                "parameters": {
                    "column_defs": [
                        ["code", [value]],
                    ]
                },
            }
        ]
    }


class ProductDefinitionSecurityTests(TestCase):
    def test_allows_literal_codes_and_the_legacy_dictionary_reference(self):
        for value in (1, "literal", "name_info['aoi_code']"):
            with self.subTest(value=value):
                definition = enum_definition(value)
                self.assertIs(
                    validate_executable_product_configuration(definition),
                    definition,
                )

    def test_rejects_function_calls_operators_and_imports(self):
        unsafe_values = (
            "name_info.get('aoi_code')",
            "name_info['aoi_code'] or __import__('os').system('id')",
            "__import__('os').system('id') if name_info else ''",
        )

        for value in unsafe_values:
            with self.subTest(value=value):
                with self.assertRaises(UnsafeProductDefinition):
                    validate_executable_product_configuration(
                        enum_definition(value)
                    )

    def test_rejects_malformed_enum_configuration(self):
        with self.assertRaises(UnsafeProductDefinition):
            validate_executable_product_configuration(
                {
                    "steps": [
                        {
                            "check_ident": "qc_tool.vector.enum",
                            "parameters": {"column_defs": [["code"]]},
                        }
                    ]
                }
            )
