"""Document discovery and parser admission independent of QC geometry rules."""

import pypdf


def find_pdfs(unzip_dir, status):

    # Find PDF files recursively without changing their contents.
    pdf_filepaths = [path for path in unzip_dir.glob("**/*")
                     if path.is_file() and path.suffix.lower() == ".pdf"]
    pdf_file_infos = []

    for pdf_filepath in pdf_filepaths:

        # Try to open PDF file...
        try:
            with open(pdf_filepath, 'rb') as f:
                reader = pypdf.PdfReader(f)
                # Try to read first page
                _ = reader.pages[0]
        except Exception as e:
            status.aborted("Can not open PDF file {:s}.".format(pdf_filepath.name))
            return []

        pdf_file_infos.append({"src_filepath": pdf_filepath, "src_filename":pdf_filepath.name})
    return pdf_file_infos
