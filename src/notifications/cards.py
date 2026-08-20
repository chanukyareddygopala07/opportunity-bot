"""Phase 15 — pure card logic for interactive Telegram messages.

Kept free of python-telegram-bot so it is trivially testable; the bot
builds the actual inline-keyboard buttons from these tuples.
"""
from src import db

SAVE = "save"
DETAILS = "det"
APPLY = "apply"


def encode(action, opp_id):
    """callback_data is limited to 64 bytes: 'save:12'."""
    return f"{action}:{opp_id}"


def decode(data):
    try:
        parts = str(data).split(":")
        if len(parts) != 2:
            return None
        action, raw_id = parts
        return action, int(raw_id)
    except (ValueError, TypeError):
        return None


def save_label(saved):
    return "💾 Saved" if saved else "🔖 Save"


def buttons(opp_id, saved=False):
    """Rows of (label, callback_data) tuples for the card keyboard."""
    return [
        [(save_label(saved), encode(SAVE, opp_id)),
         ("ℹ️ Details", encode(DETAILS, opp_id))],
        [("🔗 Apply", encode(APPLY, opp_id))],
    ]


def apply_url(opp):
    return (opp.get("application_url")
            or opp.get("official_url")
            or opp.get("source_url"))