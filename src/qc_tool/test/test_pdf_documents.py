"""Retain document admission behavior with the maintained PDF parser."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from pypdf import PdfWriter

from qc_tool.worker.documents import find_pdfs
from qc_tool.worker.status import CheckStatus


class PDFDocumentAdmissionTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="qc-pdf-documents-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.status = CheckStatus()

    def write_pdf(self, filename, *, pages=1, password=None):
        writer = PdfWriter()
        for _ in range(pages):
            writer.add_blank_page(width=72, height=72)
        if password is not None:
            writer.encrypt(password)
        path = self.directory / filename
        with path.open("wb") as handle:
            writer.write(handle)
        return path

    def test_valid_pdf_is_discovered_case_insensitively_without_changing_bytes(self):
        document = self.write_pdf("map.PDF")
        original = document.read_bytes()
        (self.directory / "notes.txt").write_text("not a PDF")
        self.assertEqual(find_pdfs(self.directory, self.status), [
            {"src_filepath": document, "src_filename": document.name},
        ])
        self.assertEqual(document.read_bytes(), original)
        self.assertFalse(self.status.messages)

    def test_corrupt_empty_and_password_protected_documents_remain_rejected(self):
        for kind in ("corrupt", "no_pages", "encrypted"):
            with self.subTest(kind=kind):
                for path in self.directory.iterdir():
                    path.unlink()
                if kind == "corrupt":
                    (self.directory / "map.pdf").write_bytes(b"%PDF-1.7\ninvalid")
                elif kind == "no_pages":
                    self.write_pdf("map.pdf", pages=0)
                else:
                    self.write_pdf("map.pdf", password="private-test-password")
                status = CheckStatus()
                self.assertEqual(find_pdfs(self.directory, status), [])
                self.assertEqual(status.status, "aborted")
                self.assertIn("Can not open PDF file map.pdf.", status.messages[0])
