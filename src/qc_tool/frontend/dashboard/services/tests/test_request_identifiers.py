from django.test import SimpleTestCase

from qc_tool.frontend.dashboard.services.requests import IdentifierListError
from qc_tool.frontend.dashboard.services.requests import (
    parse_positive_identifier_list,
)
from qc_tool.frontend.dashboard.services.requests import (
    parse_uuid_identifier_list,
)


class IdentifierListTests(SimpleTestCase):
    def test_parses_unique_bounded_integer_and_uuid_lists(self):
        self.assertEqual(parse_positive_identifier_list("1,2"), (1, 2))
        uuids = parse_uuid_identifier_list(
            "00000000-0000-0000-0000-000000000001,"
            "00000000-0000-0000-0000-000000000002"
        )
        self.assertEqual(len(uuids), 2)

    def test_rejects_empty_noncanonical_duplicate_and_oversized_lists(self):
        values = (None, "", "01", "1, 2", "1,1", "1,2")
        limits = (100, 100, 100, 100, 100, 1)
        for value, maximum in zip(values, limits):
            with self.subTest(value=value, maximum=maximum):
                with self.assertRaises(IdentifierListError):
                    parse_positive_identifier_list(
                        value,
                        maximum_items=maximum,
                    )

    def test_rejects_invalid_or_duplicate_uuids(self):
        for value in (
            "not-a-uuid",
            (
                "00000000-0000-0000-0000-000000000001,"
                "00000000-0000-0000-0000-000000000001"
            ),
        ):
            with self.subTest(value=value):
                with self.assertRaises(IdentifierListError):
                    parse_uuid_identifier_list(value)
