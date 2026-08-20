from src import db
from src.notifications import cards


class TestEncodeDecode:
    def test_roundtrip(self):
        assert cards.decode(cards.encode("save", 12)) == ("save", 12)
        assert cards.decode("det:3") == ("det", 3)
        assert cards.decode("apply:99") == ("apply", 99)

    def test_invalid(self):
        assert cards.decode(None) is None
        assert cards.decode("garbage") is None
        assert cards.decode("save:abc") is None
        assert cards.decode("save:12:extra") is None


class TestButtons:
    def test_rows(self):
        rows = cards.buttons(7, saved=False)
        assert rows[0] == [("🔖 Save", "save:7"), ("ℹ️ Details", "det:7")]
        assert rows[1] == [("🔗 Apply", "apply:7")]

    def test_saved_label(self):
        assert cards.save_label(True) == "💾 Saved"
        assert cards.save_label(False) == "🔖 Save"
        rows = cards.buttons(7, saved=True)
        assert rows[0][0] == ("💾 Saved", "save:7")

    def test_callback_data_within_64_bytes(self):
        for row in cards.buttons(2 ** 31 - 1):
            for _, data in row:
                assert len(data.encode()) <= 64


class TestApplyUrl:
    def test_priority_order(self):
        opp = {
            "application_url": "https://a.example/",
            "official_url": "https://o.example/",
            "source_url": "https://s.example/",
        }
        assert cards.apply_url(opp) == "https://a.example/"
        assert cards.apply_url({}) is None


class TestToggleSaved:
    def test_toggle(self, tmp_db):
        opp_id = db.upsert_opportunity({
            "title": "T", "organization": "O", "type": "internship",
            "application_url": "https://example.com",
        })
        assert db.toggle_saved(opp_id) is True
        assert db.get_opportunity(opp_id)["saved"] == 1
        assert db.toggle_saved(opp_id) is False
        assert db.get_opportunity(opp_id)["saved"] == 0

    def test_missing_returns_none(self, tmp_db):
        assert db.toggle_saved(999) is None