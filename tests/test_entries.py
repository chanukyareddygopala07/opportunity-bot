from pathlib import Path

from src.discovery import entries

FIXTURES = Path(__file__).parent / "fixtures"

PDF_SOURCE = {
    "name": "Test PDF Source",
    "organization": "Test Org",
    "type": "official_government",
    "category": "fellowship",
    "url": (FIXTURES / "sample_pdf_links.html").as_uri(),
    "method": "pdf_links",
    "trust_score": 100,
}


class TestFetchEntriesPdfLinks:
    def test_returns_pdf_entries_with_full_text(self):
        results = entries.fetch_entries(PDF_SOURCE)
        assert len(results) == 1
        entry = results[0]
        assert entry["title"] == "Summer Research Fellowship 2027"
        assert entry["url"].endswith("sample_notice.pdf")
        assert "Applications close on 31 December 2026" in entry["_full_text"]
        assert len(entry["description"]) <= entries.DESCRIPTION_LIMIT

    def test_non_pdf_links_are_skipped(self):
        results = entries.fetch_entries(PDF_SOURCE)
        assert all(url.lower().endswith(".pdf") for url in (r["url"] for r in results))

    def test_broken_pdf_does_not_abort_run(self, tmp_path, monkeypatch):
        import pytest

        from src import db

        monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
        db.init_db()
        page = tmp_path / "page.html"
        page.write_text('<html><a href="broken.pdf">Broken notice</a></html>')
        source = dict(PDF_SOURCE, url=page.as_uri())
        results = entries.fetch_entries(source)
        assert results == []
        conn = db.get_connection()
        row = conn.execute(
            "SELECT message FROM system_errors ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert "failed" in row[0]


class TestTitleFromPdf:
    def test_first_short_line_is_used(self):
        text = "NATIONAL FELLOWSHIP SCHEME 2026\nSome body text"
        assert entries._title_from_pdf(text, "https://x.org/notice.pdf") == (
            "NATIONAL FELLOWSHIP SCHEME 2026"
        )

    def test_filename_fallback(self):
        text = ("This first line is far too long to be used as a title for an announcement "
                "notice pdf because it exceeds one hundred and forty characters in length "
                "and therefore must be skipped by the title extractor entirely")
        assert entries._title_from_pdf(text, "https://x.org/national_scheme-2026.pdf") == (
            "national scheme 2026"
        )


class TestEnrich:
    def test_merges_extracted_fields(self):
        entry = {
            "description": (
                "Applications close on 31 December 2026. Stipend of Rs. 10,000 per month."
            )
        }
        opp = {"title": "Scheme", "organization": "Org"}
        enriched = entries.enrich(opp, entry)
        assert enriched["deadline"] == "2026-12-31"
        assert enriched["stipend"] == "Rs.10,000/month"
        assert enriched["funding"] == "Stipend provided"
        assert enriched["title"] == "Scheme"

    def test_does_not_overwrite_existing_values(self):
        entry = {"description": "Duration of 6 months. Stipend of $500 per week."}
        opp = {"stipend": "fixed", "duration": "kept"}
        enriched = entries.enrich(opp, entry)
        assert enriched["stipend"] == "fixed"
        assert enriched["duration"] == "kept"

    def test_no_fields_no_changes(self):
        entry = {"description": "Nothing extractable here."}
        opp = {"title": "T"}
        assert entries.enrich(opp, entry) == {"title": "T"}

    def test_full_text_used_over_description(self):
        entry = {
            "description": "Duration of 6 months.",
            "_full_text": "Applications close on 31 December 2026.",
        }
        enriched = entries.enrich({}, entry)
        assert enriched["deadline"] == "2026-12-31"
        assert enriched.get("duration") is None