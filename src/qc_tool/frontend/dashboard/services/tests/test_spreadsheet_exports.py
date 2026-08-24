from unittest import TestCase

from qc_tool.frontend.dashboard.services.exports import spreadsheet_cell_value


class SpreadsheetCellTests(TestCase):
    def test_neutralizes_active_formula_prefixes(self):
        for value in ("=1+1", "+cmd", "-2+3", "@SUM(A1:A2)", "\t=1"):
            with self.subTest(value=value):
                self.assertEqual(spreadsheet_cell_value(value), "'" + value)

    def test_preserves_normal_text_and_non_strings(self):
        self.assertEqual(spreadsheet_cell_value("delivery.zip"), "delivery.zip")
        self.assertEqual(spreadsheet_cell_value(42), 42)

