"""Turn invoice PDFs into Markdown: native text directly, scans through OCR."""

import pymupdf

# MuPDF prints its messages on stdout by default, which carries our results.
pymupdf.set_messages(pylogging=True)
