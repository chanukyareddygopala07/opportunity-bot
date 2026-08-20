from pathlib import Path

import pytest

from src.extraction import pdf

FIXTURES = Path(__file__).parent / "fixtures"


def test_extracts_text_from_fixture_pdf():
    data = (FIXTURES / "sample_notice.pdf").read_bytes()
    text = pdf.extract_pdf_text(data)
    assert "Applications close on 31 December 2026" in text
    assert "Rs. 10,000 per month" in text


def test_garbage_bytes_raise_value_error():
    with pytest.raises(ValueError):
        pdf.extract_pdf_text(b"this is not a pdf at all")


def test_empty_bytes_raise_value_error():
    with pytest.raises(ValueError):
        pdf.extract_pdf_text(b"")


def test_max_chars_truncates():
    data = (FIXTURES / "sample_notice.pdf").read_bytes()
    text = pdf.extract_pdf_text(data, max_chars=5)
    assert len(text) <= 5