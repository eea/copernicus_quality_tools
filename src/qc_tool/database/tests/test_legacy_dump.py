from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from qc_tool.database.legacy.dump import LegacyDumpError, read_legacy_dump


class LegacyDumpTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "source.sql"

    def parse(self, body, *, encoding="UTF8", complete=True):
        if isinstance(body, str):
            body = body.encode("utf-8")
        raw = f"SET client_encoding = '{encoding}';\n".encode() + body
        if complete:
            raw += b"-- PostgreSQL database dump complete\n"
        self.path.write_bytes(raw)
        return read_legacy_dump(self.path)

    def test_retains_copy_data_and_hashes_original_bytes(self):
        result = self.parse(
            "CREATE TABLE ignored (data text);\n"
            "COPY public.auth_user (id, username, email) FROM stdin;\n"
            "7\tfake-person\t\\N\n"
            "8\tPříliš\t\n"
            "\\.\n"
            'COPY "public"."empty_table" ("id") FROM stdin;\n'
            "\\.\n"
        )
        self.assertEqual(result.tables["auth_user"], [
            {"id": "7", "username": "fake-person", "email": None},
            {"id": "8", "username": "Příliš", "email": ""},
        ])
        self.assertEqual(result.columns["auth_user"], ("id", "username", "email"))
        self.assertEqual(result.counts, {"auth_user": 2, "empty_table": 0})
        raw = self.path.read_bytes()
        self.assertEqual(result.source_sha256, sha256(raw).hexdigest())
        self.assertEqual(result.source_size_bytes, len(raw))
        self.assertNotIn("fake-person", repr(result))
        self.assertNotIn("Příliš", repr(result))

    def test_copy_escape_sequences_and_multibyte_characters(self):
        result = self.parse(
            b"COPY public.data (value) FROM stdin;\n"
            b"a\\tb\\nc\\rd\\be\\ff\\vg\\\\h\n"
            b"\\303\\251\\xC3\\xA9\n"
            b"\\1\\12\\123\\x9\\x41\n"
            b"\\\\N\n"
            b"\\.\n"
        )
        self.assertEqual([row["value"] for row in result.tables["data"]], [
            "a\tb\nc\rd\be\ff\vg\\h", "éé", "\x01\nS\tA", "\\N",
        ])

    def test_crlf_dump(self):
        result = self.parse(b"COPY public.data (value) FROM stdin;\r\ntext\r\n\\.\r\n")
        self.assertEqual(result.tables["data"], [{"value": "text"}])

    def test_sql_and_psql_commands_are_not_executed(self):
        result = self.parse(
            "\\! deliberately-not-a-command\n"
            "DROP DATABASE production;\n"
            "COPY public.data (value) FROM stdin;\n"
            "SELECT dangerous();\n"
            "\\.\n"
        )
        self.assertEqual(result.tables["data"], [{"value": "SELECT dangerous();"}])

    def test_rejects_duplicate_tables_and_columns(self):
        for body in (
            "COPY public.data (value) FROM stdin;\n\\.\n"
            "COPY public.data (value) FROM stdin;\n\\.\n",
            'COPY public.data (value, "value") FROM stdin;\n\\.\n',
        ):
            with self.subTest(body=body), self.assertRaisesRegex(LegacyDumpError, "Duplicate COPY"):
                self.parse(body)

    def test_rejects_unsupported_copy_variants(self):
        for header in (
            "COPY public.data (value) FROM '/private/source';",
            "COPY public.data (value) FROM stdin WITH CSV;",
            "COPY public.data (value) FROM stdin WITH BINARY;",
            "COPY other.data (value) FROM stdin;",
            "COPY public.data FROM stdin;",
            "COPY public.data (value,\nsecond) FROM stdin;",
        ):
            with self.subTest(header=header), self.assertRaisesRegex(LegacyDumpError, "Unsupported COPY"):
                self.parse(header + "\n\\.\n")

    def test_rejects_insert_dump(self):
        with self.assertRaisesRegex(LegacyDumpError, "INSERT dumps are unsupported"):
            self.parse("INSERT INTO public.data VALUES ('secret');\n")

    def test_rejects_missing_copy_or_completion_marker(self):
        with self.assertRaisesRegex(LegacyDumpError, "Truncated COPY"):
            self.parse("COPY public.data (value) FROM stdin;\nsecret\n", complete=False)
        with self.assertRaisesRegex(LegacyDumpError, "completion marker"):
            self.parse("COPY public.data (value) FROM stdin;\nsecret\n\\.\n", complete=False)
        with self.assertRaisesRegex(LegacyDumpError, "No UTF-8 public-schema COPY"):
            self.parse("")

    def test_rejects_missing_or_unsupported_encoding(self):
        with self.assertRaisesRegex(LegacyDumpError, "Only UTF-8"):
            self.parse("COPY public.data (value) FROM stdin;\n\\.\n", encoding="LATIN1")
        self.path.write_bytes(b"COPY public.data (value) FROM stdin;\n\\.\n")
        with self.assertRaisesRegex(LegacyDumpError, "Unexpected COPY"):
            read_legacy_dump(self.path)

    def test_invalid_fields_never_expose_their_values(self):
        for field in (b"secret\\", b"secret\\q", b"secret\\x", b"secret\\777", b"secret\\000", b"secret\xff", b"secret\x00"):
            with self.subTest(field=field):
                with self.assertRaises(LegacyDumpError) as caught:
                    self.parse(b"COPY public.data (value) FROM stdin;\n" + field + b"\n\\.\n")
                self.assertNotIn("secret", str(caught.exception))
                self.assertIn("line 3, column 1", str(caught.exception))

    def test_rejects_column_count_mismatch(self):
        for row in ("1", "1\tsecret\textra"):
            with self.subTest(row=row), self.assertRaisesRegex(LegacyDumpError, "column count mismatch"):
                self.parse("COPY public.data (id, value) FROM stdin;\n" + row + "\n\\.\n")

    def test_rejects_invalid_utf8_outside_copy_without_exposing_it(self):
        with self.assertRaisesRegex(LegacyDumpError, "Invalid UTF-8 SQL text") as caught:
            self.parse(b"-- secret\xff\n")
        self.assertNotIn("secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
