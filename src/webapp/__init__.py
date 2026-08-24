"""Phase 17 — web front-end (replaces the Telegram bot as primary interface).

Serves the same SQLite store the pipeline writes to: browse every collected
opportunity, personalized matches per account, bookmarks, profile, stats, and
the n8n scheduler hook (POST /run with X-Run-Token).

Run: python -m src.webapp
"""
import os
from pathlib import Path

from flask import Flask, g, redirect, request, url_for

from src import db, schema
from src.envfile import load_dotenv
from src.notifications import formatting
from src.webapp import auth, views

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent


def create_app():
    db.init_db()
    # RBAC: the env-named account (if it exists yet) is promoted to admin.
    # Admin rights come only from the users.role column, never from a name.
    db.bootstrap_admin(os.environ.get("ADMIN_USERNAME", ""))
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
    )
    app.config["SECRET_KEY"] = os.environ.get("SESSION_SECRET", "dev-only")

    @app.before_request
    def load_user():
        g.user = auth.load_user(request.cookies.get(auth.SESSION_COOKIE))
        g.unread = db.unread_notification_count(g.user["id"]) if g.user else 0

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

    @app.template_filter("safe_url")
    def safe_url(value):
        """Render-time URL scheme allow-list (defense in depth against a
        poisoned source row that bypassed the write-path check)."""
        return schema.sanitize_url(value)

    @app.template_filter("elig_label")
    def elig_label(status, opp=None):
        return formatting.eligibility_label(status, opp)

    views.register_routes(app)
    return app


def _listen_port(default=8080):
    """Render/PaaS platforms inject PORT; local dev keeps 8080."""
    for var in ("PORT", "WEBAPP_PORT"):
        raw = os.environ.get(var, "").strip()
        if raw.isdigit():
            return int(raw)
    return default


def serve(host="0.0.0.0", port=None):
    port = port or _listen_port()
    app = create_app()
    # Production WSGI server when available (containers / real deployments);
    # falls back to Flask's dev server for bare local runs.
    if os.environ.get("WEBAPP_DEV_SERVER", "").strip().lower() in ("1", "true"):
        app.run(host=host, port=port, threaded=True)
        return
    try:
        from waitress import serve as waitress_serve
    except ImportError:
        app.logger.warning(
            "waitress not installed — falling back to the Flask dev server. "
            "Do NOT use this in production.")
        app.run(host=host, port=port, threaded=True)
        return
    threads = int(os.environ.get("WEBAPP_THREADS", "8"))
    waitress_serve(
        app, host=host, port=port, threads=threads,
        # Behind Render/NGINX-style proxies, trust X-Forwarded-Proto so
        # COOKIE_SECURE=auto sees HTTPS correctly.
        url_scheme=os.environ.get("WEBAPP_URL_SCHEME", "http"),
    )


if __name__ == "__main__":
    serve()
