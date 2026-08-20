"""Store facade — SQLite-backed since Phase 3. Same API the bot always used."""
import json
import os
from pathlib import Path

from src import db

CONFIG_DIR = Path(os.environ.get("OPP_CONFIG_DIR", Path(__file__).resolve().parent.parent / "config"))
PROFILE_FILE = CONFIG_DIR / "profile.json"


def _seed_from_profile_file():
    if not PROFILE_FILE.exists():
        return None
    profile = json.loads(PROFILE_FILE.read_text())
    db.upsert_user(profile)
    return db.get_default_user()


def load_profile(chat_id=None):
    user = None
    if chat_id is not None:
        user = db.get_user_by_chat(chat_id)
    if user is None:
        user = db.get_default_user()
    if user is None:
        user = _seed_from_profile_file()
    return user or {}


def reset_profile(chat_id=None):
    if not PROFILE_FILE.exists():
        return
    profile = json.loads(PROFILE_FILE.read_text())
    db.upsert_user(profile, chat_id=chat_id)
    return db.get_user_by_chat(chat_id) if chat_id else db.get_default_user()


def load_opportunities():
    return db.list_opportunities()


def save_opportunities(items):
    for item in items:
        db.upsert_opportunity(item)