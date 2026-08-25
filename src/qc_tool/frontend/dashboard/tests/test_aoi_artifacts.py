from io import BytesIO
from unittest.mock import patch
from uuid import UUID

from django.test import SimpleTestCase

from qc_tool.frontend.dashboard.services.aoi import AoiResultUnavailable
from qc_tool.frontend.dashboard.services.aoi import load_aoi_result_document


class AoiResultArtifactTests(SimpleTestCase):
    @patch(
        "qc_tool.frontend.dashboard.services.aoi.artifacts."
        "open_regular_artifact"
    )
    def test_loads_a_bounded_json_object(self, opener):
        opener.return_value = BytesIO(b'{"aoi_code":"EE003L1"}')

        document = load_aoi_result_document(UUID(int=1), maximum_bytes=64)

        self.assertEqual(document, {"aoi_code": "EE003L1"})

    @patch(
        "qc_tool.frontend.dashboard.services.aoi.artifacts."
        "open_regular_artifact"
    )
    def test_rejects_oversized_or_non_object_documents(self, opener):
        for payload, maximum_bytes in (
            (b'{"aoi_code":"too-large"}', 8),
            (b"[]", 8),
            (b"not-json", 16),
        ):
            with self.subTest(payload=payload):
                opener.return_value = BytesIO(payload)
                with self.assertRaises(AoiResultUnavailable):
                    load_aoi_result_document(
                        UUID(int=1),
                        maximum_bytes=maximum_bytes,
                    )
