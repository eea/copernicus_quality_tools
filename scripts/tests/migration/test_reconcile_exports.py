"""Synthetic source comparisons and XLSX rejection checks; no DB or network."""

import contextlib
import copy
import csv
from datetime import datetime
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from scripts.migration.legacy import reconcile_exports as reconciliation


SHEET_NS = reconciliation.NS['s']
REL_NS = reconciliation.NS['r']
PACKAGE_REL_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'


def excel_timestamp(value):
    local = datetime.fromisoformat(value).replace(tzinfo=None)
    return str((local - datetime(1899, 12, 30)).total_seconds() / 86400)


class ExportReconciliationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.delivery = {
            'id': '42', 'filename': 'synthetic.zip', 'username': 'synthetic-owner',
            'date_uploaded': '2026-01-01T12:00:00+01:00', 'size_bytes': '48',
            'product_ident': 'synthetic_product', 'product_description': 'Synthetic μ',
            'date_submitted': '', 'is_deleted': 'f', 's3_id': '', 'aoi_code': 'mt',
            'user_id': '1',
        }
        self.job = {
            'job_uuid': 'latest-job', 'delivery_id': '42',
            'date_created': '2026-01-02T12:00:00+01:00',
            'date_started': '2026-01-02T12:00:00+01:00',
            'job_status': 'ok', 'worker_url': 'https://worker.invalid/',
        }
        self.users = {'1': {'username': 'synthetic-owner'}}
        self.export = {column: '' for column in reconciliation.EXPORT_COLUMNS}
        self.export.update({field: self.delivery[field] for field in reconciliation.DELIVERY_FIELDS})
        self.export.update(
            id='42', username='synthetic-owner', is_deleted='0',
            date_uploaded=excel_timestamp(self.delivery['date_uploaded']),
            last_job_uuid=self.job['job_uuid'], last_job_worker_url=self.job['worker_url'],
            date_created=excel_timestamp(self.job['date_created']),
            date_started=excel_timestamp(self.job['date_started']), last_job_status='ok',
        )

    def write_xlsx(self, rows, *, filename='export.xlsx', headers=None,
                   sheet_name='Deliveries', date1904=False, formula=False,
                   include_header=True):
        """Write actual OOXML with inline/shared strings and scalar numbers."""
        workbook = ET.Element(f'{{{SHEET_NS}}}workbook')
        if date1904:
            ET.SubElement(workbook, f'{{{SHEET_NS}}}workbookPr', date1904='true')
        sheets = ET.SubElement(workbook, f'{{{SHEET_NS}}}sheets')
        ET.SubElement(sheets, f'{{{SHEET_NS}}}sheet', {
            'name': sheet_name, 'sheetId': '1', f'{{{REL_NS}}}id': 'rId1',
        })
        relationships = ET.Element(f'{{{PACKAGE_REL_NS}}}Relationships')
        ET.SubElement(relationships, f'{{{PACKAGE_REL_NS}}}Relationship', {
            'Id': 'rId1', 'Target': 'worksheets/sheet1.xml', 'Type': REL_NS + '/worksheet',
        })
        shared = ET.Element(f'{{{SHEET_NS}}}sst')
        item = ET.SubElement(shared, f'{{{SHEET_NS}}}si')
        for text in ('synthetic-', 'owner'):
            run = ET.SubElement(item, f'{{{SHEET_NS}}}r')
            ET.SubElement(run, f'{{{SHEET_NS}}}t').text = text
        sheet = ET.Element(f'{{{SHEET_NS}}}worksheet')
        data = ET.SubElement(sheet, f'{{{SHEET_NS}}}sheetData')
        columns = headers or reconciliation.EXPORT_COLUMNS
        source_rows = [dict(zip(reconciliation.EXPORT_COLUMNS, columns))] if include_header else []
        source_rows.extend(rows)
        numeric = {'id', 'size_bytes', 'is_deleted', 'date_uploaded', 'date_created', 'date_started'}
        for ordinal, values in enumerate(source_rows, start=1):
            row = ET.SubElement(data, f'{{{SHEET_NS}}}row', r=str(ordinal))
            for index, column in enumerate(reconciliation.EXPORT_COLUMNS):
                cell = ET.SubElement(row, f'{{{SHEET_NS}}}c', r=f'{chr(65 + index)}{ordinal}')
                value = values.get(column, '')
                if ordinal > 1 and column == 'username':
                    cell.set('t', 's')
                    ET.SubElement(cell, f'{{{SHEET_NS}}}v').text = '0'
                elif ordinal > 1 and column in numeric and value:
                    ET.SubElement(cell, f'{{{SHEET_NS}}}v').text = value
                else:
                    cell.set('t', 'inlineStr')
                    inline = ET.SubElement(cell, f'{{{SHEET_NS}}}is')
                    ET.SubElement(inline, f'{{{SHEET_NS}}}t').text = value
                if formula and ordinal > 1 and column == 'filename':
                    ET.SubElement(cell, f'{{{SHEET_NS}}}f').text = 'PRIVATE_FORMULA()'
        path = self.directory / filename
        with ZipFile(path, 'w') as archive:
            for member, tree in (
                ('xl/workbook.xml', workbook), ('xl/_rels/workbook.xml.rels', relationships),
                ('xl/sharedStrings.xml', shared), ('xl/worksheets/sheet1.xml', sheet),
            ):
                archive.writestr(member, ET.tostring(tree, encoding='utf-8', xml_declaration=True))
        return path

    def reconcile(self, exports, *, deliveries=None, jobs=None, **kwargs):
        return reconciliation.reconcile(
            deliveries or {'42': self.delivery}, jobs if jobs is not None else {'latest-job': self.job},
            exports, **kwargs,
        )

    def test_xlsx_reads_rich_shared_inline_numeric_and_empty_cells_without_changes(self):
        path = self.write_xlsx([self.export])
        before = path.read_bytes()
        rows = reconciliation.read_xlsx(path)
        self.assertEqual(rows, [self.export])
        self.assertEqual(rows[0]['product_description'], 'Synthetic μ')
        self.assertEqual(rows[0]['size_bytes'], '48')
        self.assertEqual(rows[0]['date_submitted'], '')
        self.assertEqual(path.read_bytes(), before)

    def test_latest_job_and_local_excel_time_reconcile_without_mutating_sources(self):
        old = {**self.job, 'job_uuid': 'older-job', 'date_created': '2025-12-01T12:00:00+01:00'}
        jobs = {'latest-job': self.job, 'older-job': old}
        inputs = ({'42': self.delivery}, jobs, [self.export], self.users)
        original = copy.deepcopy(inputs)
        report = self.reconcile(inputs[2], jobs=jobs, expected_active_count=1, users=self.users)
        self.assertTrue(report['complete_reconciliation'])
        self.assertEqual(report['changed_field_counts'], {})
        self.assertEqual(report['original_jobs'], 2)
        self.assertEqual(report['exported_last_job_status_counts'], {'ok': 1})
        self.assertEqual(inputs, original)

    def test_missing_declared_scope_or_owner_cannot_certify_matching_rows(self):
        for arguments, unresolved in (({'users': self.users}, 0),
                                      ({'expected_active_count': 2, 'users': self.users}, 0),
                                      ({'expected_active_count': 1}, 1)):
            with self.subTest(arguments=arguments):
                report = self.reconcile([self.export], **arguments)
                self.assertFalse(report['complete_reconciliation'])
                self.assertEqual(report['overlapping_owner_references_unresolved'], unresolved)
                self.assertEqual(report['changed_field_counts'], {})

    def test_duplicate_new_and_absent_deliveries_remain_separate_gaps(self):
        deliveries = {'42': self.delivery, '43': {**self.delivery, 'id': '43'}}
        new = {**self.export, 'id': '99', 'last_job_uuid': ''}
        report = self.reconcile([self.export, dict(self.export), new], deliveries=deliveries,
                                expected_active_count=2, users=self.users)
        self.assertEqual(report['duplicate_exported_rows'], 1)
        self.assertEqual(report['unique_exported_deliveries'], 2)
        self.assertEqual(report['new_delivery_ids_without_full_original_metadata'], 1)
        self.assertEqual(report['original_active_ids_absent_from_exports'], 1)
        self.assertFalse(report['declared_scope_count_matches'])
        self.assertFalse(report['complete_reconciliation'])

    def test_changed_delivery_and_unknown_latest_job_are_reported_by_field(self):
        changed = {**self.export, 'size_bytes': '49', 'last_job_uuid': 'unrecorded-job',
                   'last_job_status': 'failed', 'date_uploaded': str(float(self.export['date_uploaded']) + 1)}
        report = self.reconcile([changed], expected_active_count=1, users=self.users)
        self.assertEqual(report['exported_jobs_absent_from_original_history'], 1)
        self.assertEqual(report['changed_overlapping_delivery_rows'], 1)
        self.assertEqual(report['changed_field_counts'], {
            'date_uploaded': 1, 'last_job_status': 1, 'last_job_uuid': 1, 'size_bytes': 1,
        })
        self.assertFalse(report['complete_reconciliation'])

    def test_unsupported_xlsx_contracts_fail_without_exposing_source_values(self):
        malformed = (
            {'formula': True}, {'date1904': True}, {'sheet_name': 'PRIVATE_SHEET'},
            {'headers': ('PRIVATE_HEADER', *reconciliation.EXPORT_COLUMNS[1:])},
            {'include_header': False},
        )
        for index, options in enumerate(malformed):
            with self.subTest(options=options):
                path = self.write_xlsx([] if options.get('include_header') is False else [self.export],
                                       filename=f'malformed-{index}.xlsx', **options)
                before = path.read_bytes()
                with self.assertRaises(reconciliation.ReconciliationError) as failure:
                    reconciliation.read_xlsx(path)
                self.assertNotIn('PRIVATE', str(failure.exception))
                self.assertEqual(path.read_bytes(), before)
        with self.assertRaisesRegex(reconciliation.ReconciliationError, 'boolean'):
            self.reconcile([{**self.export, 'is_deleted': 'false'}], users=self.users)

    def test_original_csv_rejects_duplicate_missing_keys_and_extra_cells(self):
        for index, rows in enumerate((('42,value', '42,second'), (',value',), ('42,value,extra',))):
            with self.subTest(rows=rows):
                path = self.directory / f'malformed-{index}.csv'
                path.write_text('id,filename\n' + '\n'.join(rows) + '\n')
                with self.assertRaises(reconciliation.ReconciliationError):
                    reconciliation.read_csv(path, 'id', {'id', 'filename'})

    def test_cli_reconciles_actual_csv_dump_and_xlsx_keeps_bytes_and_prints_aggregates(self):
        sources = []
        for name, row in (('delivery.csv', self.delivery), ('job.csv', self.job)):
            path = self.directory / name
            with path.open('w', newline='', encoding='utf-8') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(row))
                writer.writeheader()
                writer.writerow(row)
            sources.append(path)
        dump = self.directory / 'users.sql'
        dump.write_text("SET client_encoding = 'UTF8';\nCOPY public.auth_user (id, username) FROM stdin;\n1\tsynthetic-owner\n\\.\n-- PostgreSQL database dump complete\n")
        export = self.write_xlsx([self.export])
        sources.extend((dump, export))
        originals = {path: path.read_bytes() for path in sources}
        output = io.StringIO()
        arguments = ['reconcile', '--delivery-csv', str(sources[0]), '--job-csv', str(sources[1]),
                     '--legacy-dump', str(dump), '--expected-active-count', '1', str(export)]
        with patch('sys.argv', arguments), contextlib.redirect_stdout(output):
            result = reconciliation.main()
        self.assertEqual(result, 0)
        report = json.loads(output.getvalue())
        self.assertTrue(report['complete_reconciliation'])
        self.assertEqual(len(report['sources']), 4)
        self.assertNotIn('synthetic-owner', output.getvalue())
        self.assertNotIn('synthetic.zip', output.getvalue())
        for path, original in originals.items():
            self.assertEqual(path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
