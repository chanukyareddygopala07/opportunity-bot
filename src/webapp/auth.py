"""Web app authentication: scrypt password hashing + DB-backed sessions."""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from src import db

SESSION_COOKIE = "opp_session"
SESSION_DAYS = 30


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt.encode(), n=2 ** 14, r=8, p=1, dklen=32
    )
    return f"scrypt${salt}${digest.hex()}"


def verify_password(password, stored):
    if not stored:
        return False
    try:
        method, salt, expected = stored.split("$")
    except ValueError:
        return False
    if method != "scrypt":
        return False
    digest = hashlib.scrypt(
        password.encode(), salt=salt.encode(), n=2 ** 14, r=8, p=1, dklen=32
    )
    return hmac.compare_digest(digest.hex(), expected)


def _expiry():
    return (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat()


def start_session(user_id):
    token = secrets.token_urlsafe(32)
    db.create_session(user_id, token, _expiry())
    return token


def end_session(token):
    if token:
        db.delete_session(token)


def load_user(token):
    if not token:
        return None
    session = db.get_session(token)
    if not session:
        return None
    if session.get("expires_at") and session["expires_at"] < db.now_iso():
        db.delete_session(token)
        return None
    return db.get_user_by_id(session["user_id"])
