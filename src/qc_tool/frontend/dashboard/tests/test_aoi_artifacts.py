from io import BytesIO
from unittest.mock import patch
from uuid import UUID

from django.test import SimpleTestCase

from qc_tool.frontend.dashboard.services.product_units import ProductUnitResultUnavailable
from qc_tool.frontend.dashboard.services.product_units import load_product_unit_result_document


class ProductUnitResultArtifactTests(SimpleTestCase):
    @patch(
        "qc_tool.frontend.dashboard.services.product_units.artifacts."
        "open_regular_artifact"
    )
    def test_loads_a_bounded_json_object(self, opener):
        opener.return_value = BytesIO(b'{"product_unit_code":"EE003L1"}')

        document = load_product_unit_result_document(UUID(int=1), maximum_bytes=64)

        self.assertEqual(document, {"product_unit_code": "EE003L1"})

    @patch(
        "qc_tool.frontend.dashboard.services.product_units.artifacts."
        "open_regular_artifact"
    )
    def test_rejects_oversized_or_non_object_documents(self, opener):
        for payload, maximum_bytes in (
            (b'{"product_unit_code":"too-large"}', 8),
            (b"[]", 8),
            (b"not-json", 16),
        ):
            with self.subTest(payload=payload):
                opener.return_value = BytesIO(payload)
                with self.assertRaises(ProductUnitResultUnavailable):
                    load_product_unit_result_document(
                        UUID(int=1),
                        maximum_bytes=maximum_bytes,
                    )
