"""Phase 17 — web front-end (replaces the Telegram bot as primary interface).

Serves the same SQLite store the pipeline writes to: browse every collected
opportunity, personalized matches per account, bookmarks, profile, stats, and
the n8n scheduler hook (POST /run with X-Run-Token).

Run: python -m src.webapp
"""
import os
from pathlib import Path

from flask import Flask, g, redirect, request, url_for

from src import db
from src.notifications import formatting
from src.webapp import auth, views

BASE_DIR = Path(__file__).resolve().parent


def create_app():
    db.init_db()
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
    )
    app.config["SECRET_KEY"] = os.environ.get("SESSION_SECRET", "dev-only")

    @app.before_request
    def load_user():
        g.user = auth.load_user(request.cookies.get(auth.SESSION_COOKIE))

    @app.template_filter("days_left")
    def days_left(value):
        return formatting.deadline_days_left(value)

    @app.template_filter("short_date")
    def short_date(value):
        if not value:
            return ""
        return str(value)[:10]

    @app.template_filter("list_date")
    def list_date(value):
        return formatting.format_listed(value) or ""

    @app.template_filter("priority")
    def priority(value):
        return formatting.priority_emoji(value)

    @app.template_filter("lines")
    def lines(value):
        return (value or "").replace("\n", "<br>")

    @app.template_filter("elig_label")
    def elig_label(status, opp=None):
        return formatting.eligibility_label(status, opp)

    views.register_routes(app)
    return app


def serve(host="0.0.0.0", port=8080):
    app = create_app()
    app.run(host=host, port=port, threaded=True)


if __name__ == "__main__":
    serve()
