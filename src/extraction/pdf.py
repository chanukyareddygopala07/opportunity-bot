"""Phase 8 — local PDF text extraction (pypdf, free, offline)."""
from io import BytesIO

import pypdf


def extract_pdf_text(pdf_bytes, max_chars=20000):
    try:
        reader = pypdf.PdfReader(BytesIO(pdf_bytes))
    except Exception as exc:
        raise ValueError(f"PDF parse failed: {exc}") from exc
    parts = []
    total = 0
    for page in reader.pages[:10]:
        text = page.extract_text() or ""
        parts.append(text)
        total += len(text)
        if total >= max_chars:
            break
    return "\n".join(parts)[:max_chars]