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



class TabularSerializationTests(TestCase):
    def test_formats_have_one_order_and_keep_the_existing_default(self):
        from qc_tool.frontend.dashboard.services.exports import EXPORT_FORMAT_OPTIONS, EXPORT_FORMATS, export_format

        self.assertEqual(EXPORT_FORMATS, ("json", "csv", "xlsx", "xml"))
        self.assertEqual(EXPORT_FORMAT_OPTIONS, tuple(
            {"value": value, "label": value.upper()} for value in EXPORT_FORMATS
        ))
        self.assertEqual(export_format(None), "xlsx")

    def test_excel_continues_on_new_sheets_with_repeated_headers(self):
        import io
        from unittest.mock import patch
        import openpyxl
        from qc_tool.frontend.dashboard.services.exports import ExportColumn
        from qc_tool.frontend.dashboard.services.exports.tabular import write_xlsx

        output = io.BytesIO()
        with patch("qc_tool.frontend.dashboard.services.exports.tabular.XLSX_MAX_ROWS", 3):
            write_xlsx(({"id": number} for number in range(5)), [ExportColumn("id", "ID")], output)
        workbook = openpyxl.load_workbook(io.BytesIO(output.getvalue()), read_only=True)
        try:
            self.assertEqual([list(sheet.values) for sheet in workbook], [
                [("ID",), (0,), (1,)], [("ID",), (2,), (3,)], [("ID",), (4,)],
            ])
        finally:
            workbook.close()

    def test_cancelled_csv_closes_its_row_iterator(self):
        from qc_tool.frontend.dashboard.services.exports import ExportColumn
        from qc_tool.frontend.dashboard.services.exports.tabular import csv_chunks

        closed = []
        def rows():
            try:
                yield {"id": 1}
                yield {"id": 2}
            finally:
                closed.append(True)

        stream = csv_chunks(rows(), [ExportColumn("id", "ID")])
        next(stream)  # UTF-8 BOM
        next(stream)  # Header
        next(stream)  # First row
        stream.close()
        self.assertEqual(closed, [True])

    def test_cancelled_json_and_xml_close_their_row_iterators(self):
        from qc_tool.frontend.dashboard.services.exports import ExportColumn
        from qc_tool.frontend.dashboard.services.exports.tabular import json_chunks, xml_chunks

        for chunks in (json_chunks, xml_chunks):
            with self.subTest(format=chunks.__name__):
                closed = []

                def rows():
                    try:
                        yield {"id": "first record"}
                        yield {"id": "second record"}
                    finally:
                        closed.append(True)

                stream = chunks(rows(), [ExportColumn("id", "ID")])
                for chunk in stream:
                    if "first record" in chunk:
                        break
                stream.close()
                self.assertEqual(closed, [True])

    def test_json_preserves_values_and_declared_column_order(self):
        import json
        from datetime import datetime, timezone
        from uuid import UUID
        from qc_tool.frontend.dashboard.services.exports import ExportColumn
        from qc_tool.frontend.dashboard.services.exports.tabular import json_chunks

        timestamp = datetime(2026, 9, 10, 12, 30, tzinfo=timezone.utc)
        identifier = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        row = {"name": "\x00=SUM(1,2) <literal>", "nested": {"items": [True, None, 42, "Čeština"]},
               "empty": None, "number": -42, "enabled": False, "date": timestamp, "id": identifier,
               "private": "never exported"}
        fields = ("id", "date", "name", "nested", "empty", "number", "enabled")
        columns = [ExportColumn(field, field) for field in fields]
        columns.append(ExportColumn("derived", "Calculated", lambda row: {"source": row["name"]}))
        records = json.loads("".join(json_chunks(iter([row]), columns)))
        self.assertEqual(list(records[0]), [*fields, "derived"])
        self.assertEqual(records, [{
            "id": str(identifier), "date": "2026-09-10T12:30:00Z", "name": row["name"],
            "nested": row["nested"], "empty": None, "number": -42, "enabled": False,
            "derived": {"source": row["name"]},
        }])
        self.assertEqual("".join(json_chunks(iter([]), columns)), "[]")

    def test_xml_preserves_cell_types_and_escapes_arbitrary_fields_and_values(self):
        import json
        from datetime import date
        from uuid import UUID
        from xml.etree import ElementTree
        from qc_tool.frontend.dashboard.services.exports import ExportColumn
        from qc_tool.frontend.dashboard.services.exports.tabular import xml_chunks

        identifier = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        name = 'field <&" with spaces'
        row = {name: "\x00\ud800\ufffe=1 < 2 & \"Čeština\"", "missing": None, "empty": "",
               "boolean": False, "number": -42, "metadata": {"nested": [True, None, "a<&b"]},
               "date": date(2026, 9, 10), "id": identifier, "private": "never exported"}
        columns = [ExportColumn(field, 'Label <&"\x00') for field in row if field != "private"]
        columns.append(ExportColumn("derived", "Calculated", lambda row: 12.5))
        document = ElementTree.fromstring("".join(xml_chunks(iter([row]), columns)))
        self.assertEqual(document.tag, "table")
        self.assertEqual([column.attrib["field"] for column in document.find("columns")],
                         [column.field for column in columns])
        self.assertEqual(document.find("columns/column").attrib["label"], 'Label <&"')
        cells = document.findall("rows/row/cell")
        self.assertEqual([cell.attrib["type"] for cell in cells],
                         ["string", "null", "string", "boolean", "number", "json", "string", "string", "number"])
        self.assertEqual(cells[0].text, '=1 < 2 & "Čeština"')
        self.assertIsNone(cells[1].text)
        self.assertEqual(cells[3].text, "false")
        self.assertEqual(cells[4].text, "-42")
        self.assertEqual(json.loads(cells[5].text), row["metadata"])
        self.assertEqual(cells[6].text, "2026-09-10")
        self.assertEqual(cells[7].text, str(identifier))
        self.assertEqual(cells[8].text, "12.5")
        empty = ElementTree.fromstring("".join(xml_chunks(iter([]), columns)))
        self.assertEqual(len(empty.find("columns")), len(columns))
        self.assertEqual(list(empty.find("rows")), [])

    def test_shared_csv_and_xlsx_preserve_metadata_and_neutralize_formulas(self):
        import csv
        import io
        import json
        from datetime import datetime, timezone
        from uuid import UUID
        import openpyxl
        from qc_tool.frontend.dashboard.services.exports import ExportColumn
        from qc_tool.frontend.dashboard.services.exports.tabular import csv_chunks, write_xlsx

        identifier = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        timestamp = datetime(2026, 9, 10, 12, 30, tzinfo=timezone.utc)
        columns = tuple(ExportColumn(key, key) for key in ("id", "date", "metadata", "text", "number", "missing", "derived"))
        columns = columns[:-1] + (ExportColumn("derived", "derived", lambda row: "=SUM(1,2)"),)
        row = {"id": identifier, "date": timestamp, "metadata": {"name": "Čeština", "id": identifier},
               "text": "\x00=1+1", "number": -42, "private": "not exported"}
        csv_rows = list(csv.reader(io.StringIO("".join(csv_chunks(iter([row]), columns)).lstrip("\ufeff"))))
        self.assertEqual(csv_rows[1], [str(identifier), timestamp.isoformat(),
                                      json.dumps(row["metadata"], default=str, ensure_ascii=False),
                                      "'=1+1", "-42", "", "'=SUM(1,2)"])
        output = io.BytesIO()
        write_xlsx(iter([row]), columns, output)
        workbook = openpyxl.load_workbook(io.BytesIO(output.getvalue()))
        try:
            cells = list(workbook.active.rows)[1]
            self.assertEqual([cell.value for cell in cells], csv_rows[1][:4] + [-42, None, "'=SUM(1,2)"])
            self.assertFalse(any(cell.data_type == "f" for cell in cells))
        finally:
            workbook.close()
