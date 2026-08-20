"""Shared Telegram sender (stdlib-only) for the bot and later n8n workflows."""
import json
import logging
import os
import time
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)
API_BASE = "https://api.telegram.org"


def get_bot_token():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    return token


def get_chat_id():
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not chat_id:
        raise RuntimeError("TELEGRAM_CHAT_ID is not set; send /start to the bot once")
    return chat_id


def send_message(text, chat_id=None, token=None, parse_mode="HTML", reply_markup=None):
    token = token or get_bot_token()
    chat_id = chat_id or get_chat_id()
    params = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    if reply_markup is not None:
        params["reply_markup"] = json.dumps(reply_markup)
    payload = urllib.parse.urlencode(params).encode()
    url = f"{API_BASE}/bot{token}/sendMessage"
    req = urllib.request.Request(url, data=payload)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except Exception as exc:
            logger.warning("sendMessage attempt %d failed: %s", attempt + 1, exc)
            time.sleep(2 ** attempt)
    raise RuntimeError("Telegram sendMessage failed after 3 attempts")