"""Phase 13 — single entry point: Telegram poller + n8n webhook side by side."""
import threading

from src import webhook
from src.notifications import telegram_bot

WEBHOOK_HOST = "0.0.0.0"
WEBHOOK_PORT = int(__import__("os").environ.get("WEBHOOK_PORT", "8080"))


def main():
    threading.Thread(
        target=webhook.serve,
        args=(WEBHOOK_HOST, WEBHOOK_PORT),
        daemon=True,
        name="webhook",
    ).start()
    telegram_bot.main()


if __name__ == "__main__":
    main()