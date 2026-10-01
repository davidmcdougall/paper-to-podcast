"""Bounded text-PDF extraction, run in a disposable subprocess by the app."""
import io
import json
import sys
from pypdf import PdfReader, filters

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PAGES = 100
MAX_TEXT_CHARS = 500_000
MAX_STREAM_BYTES = 5 * 1024 * 1024


def extract(data):
    if len(data) > MAX_PDF_BYTES or not data.startswith(b'%PDF-'):
        raise ValueError('Supply a PDF no larger than 20 MiB.')
    filters.ZLIB_MAX_OUTPUT_LENGTH = MAX_STREAM_BYTES
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise ValueError('Password-protected PDFs are not supported.')
    if len(reader.pages) > MAX_PAGES:
        raise ValueError('PDFs are limited to 100 pages; upload the relevant paper or chapter.')
    pages, total = [], 0
    for page in reader.pages:
        contents = page.get_contents()
        if contents is not None and len(contents.get_data()) > MAX_STREAM_BYTES:
            raise ValueError('PDF page is too complex to extract safely.')
        text = page.extract_text() or ''
        total += len(text)
        if total > MAX_TEXT_CHARS:
            raise ValueError('Extracted text exceeds 500,000 characters; upload a shorter source.')
        pages.append(text)
    text = '\n'.join(pages)
    if len(text.strip()) < 200:
        raise ValueError('Could not extract text — this may be a scanned/image PDF. OCR is not supported.')
    return text


if __name__ == '__main__':
    try:
        print(json.dumps({'text': extract(sys.stdin.buffer.read(MAX_PDF_BYTES+1))}))
    except Exception:
        # Do not send parser internals or untrusted document strings to the browser.
        print(json.dumps({'error': 'Unreadable, encrypted, scanned, oversized or overly complex PDF. Use a text PDF under 20 MiB / 100 pages.'}))
        sys.exit(1)
