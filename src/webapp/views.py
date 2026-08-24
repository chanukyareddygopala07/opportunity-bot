"""Web app routes: pages for browsing, auth, profile, stats, pipeline trigger."""
import hashlib
import hmac
import json
import os
import re
import secrets
import time

from flask import (
    Response,
    abort,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from src import db, store, webhook, worker, ai, deadlines, trust, schema
from src.webapp import auth, helpers, oauth


def _login_required(view):
    def wrapped(*args, **kwargs):
        if not g.user:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    wrapped.__name__ = view.__name__
    return wrapped


def _admin_sources():
    from src import sources as registry
    registry.sync_sources()
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, url, method, category, enabled, priority, "
            "consecutive_failures, cooldown_until FROM sources ORDER BY name"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _admin_users():
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT id, username, email, created_at, "
            "(SELECT COUNT(*) FROM bookmarks b WHERE b.user_id = u.id) AS saved, "
            "(SELECT COUNT(*) FROM applications a WHERE a.user_id = u.id) AS apps "
            "FROM users u ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _safe_next(value):
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return None


def _admin_required(view):
    def wrapped(*args, **kwargs):
        if not g.user or g.user.get("role") != "admin":
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    wrapped.__name__ = view.__name__
    return wrapped


def _public_base_url():
    """Canonical public origin: PUBLIC_BASE_URL env when set (recommended in
    production), else the request's own root. Host headers are untrusted."""
    configured = (os.environ.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if configured:
        return configured
    return request.url_root.rstrip("/")


def _cookie_secure(request):
    """Secure flag policy: COOKIE_SECURE=force|never|auto (default).

    auto enables Secure whenever the request arrived over HTTPS (directly or
    via a proxy's X-Forwarded-Proto), so plain-HTTP localhost keeps working.
    """
    mode = os.environ.get("COOKIE_SECURE", "auto").strip().lower()
    if mode == "force":
        return True
    if mode == "never":
        return False
    return request.is_secure or request.headers.get("X-Forwarded-Proto") == "https"


def _set_session_cookie(response, token):
    response.set_cookie(
        auth.SESSION_COOKIE,
        token,
        max_age=auth.SESSION_DAYS * 24 * 3600,
        httponly=True,
        samesite="Lax",
        secure=_cookie_secure(request),
    )
    return response


_AUTH_ATTEMPTS = {}
_AUTH_MAX_ATTEMPTS = 10
_AUTH_WINDOW_SECONDS = 600

# Rudra chat throttling (per user+IP).
_RUDRA_ATTEMPTS = {}
_RUDRA_MAX_MESSAGES = 20
_RUDRA_WINDOW_SECONDS = 600

_RUDRA_FLAG_CACHE = {"value": None}


def _rudra_widget_enabled():
    """Feature flag: RUDRA_WIDGET_ENABLED=true|false|auto (default auto).

    auto keeps the widget available whenever any AI provider could answer;
    providers are checked cheaply (env keys / Ollama URL configured) without
    network pings in the page-render path.
    """
    if _RUDRA_FLAG_CACHE["value"] is None:
        raw = os.environ.get("RUDRA_WIDGET_ENABLED", "auto").strip().lower()
        if raw == "false":
            _RUDRA_FLAG_CACHE["value"] = False
        elif raw == "true":
            _RUDRA_FLAG_CACHE["value"] = True
        else:  # auto
            has_provider = bool(
                os.environ.get("GROQ_API_KEY", "").strip()
                or os.environ.get("OPENAI_API_KEY", "").strip()
                or os.environ.get("GEMINI_API_KEY", "").strip()
                or os.environ.get("OLLAMA_URL", "").strip()
                or ai.DEFAULT_URL
            )
            _RUDRA_FLAG_CACHE["value"] = has_provider
    return _RUDRA_FLAG_CACHE["value"]


def _rudra_history():
    """Latest conversation's messages for widget hydration (whitelisted fields)."""
    try:
        rows = db.get_chat_history(g.user["id"], limit=30)
    except Exception:
        return []
    return [
        {"role": r.get("role"), "content": (r.get("content") or "")[:2000],
         "conversation_id": r.get("conversation_id")}
        for r in rows
        if r.get("role") in ("user", "assistant")
    ]


def _login_required_json(view):
    def wrapped(*args, **kwargs):
        if not g.user:
            return jsonify({"error": "authentication required"}), 401
        return view(*args, **kwargs)

    wrapped.__name__ = view.__name__
    return wrapped

# Anonymous abuse-report throttling (per IP).
_REPORT_ATTEMPTS = {}
_REPORT_MAX = 5
_REPORT_WINDOW_SECONDS = 3600


def _throttled(store_, key, max_attempts, window_seconds):
    now = time.time()
    window = [t for t in store_.get(key, []) if now - t < window_seconds]
    store_[key] = window
    return len(window) >= max_attempts


def _note_attempt(store_, key):
    store_.setdefault(key, []).append(time.time())


def _auth_is_blocked():
    key = request.remote_addr or "unknown"
    return _throttled(_AUTH_ATTEMPTS, key, _AUTH_MAX_ATTEMPTS, _AUTH_WINDOW_SECONDS)


def _auth_note_failure():
    _note_attempt(_AUTH_ATTEMPTS, request.remote_addr or "unknown")


def _report_is_blocked():
    key = request.remote_addr or "unknown"
    return _throttled(_REPORT_ATTEMPTS, key, _REPORT_MAX, _REPORT_WINDOW_SECONDS)


def _auth_provider_configured(provider):
    if provider == "google":
        return bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))
    if provider == "github":
        return bool(os.environ.get("GITHUB_CLIENT_ID") and os.environ.get("GITHUB_CLIENT_SECRET"))
    return False


# Names that can never be registered; admin rights come exclusively from the
# users.role column, which only db.bootstrap_admin (env-configured) grants.
RESERVED_USERNAMES = frozenset({
    "admin", "administrator", "root", "support", "moderator", "mod",
    "staff", "official", "aawara", "security", "system",
})

ANON_CSRF_COOKIE = "opp_csrf"


def _secret_key_bytes():
    try:
        from flask import current_app
        key = current_app.config.get("SECRET_KEY")
    except RuntimeError:
        key = None
    if not key:
        key = os.environ.get("SESSION_SECRET", "dev-only")
    return str(key).encode()


def csrf_token_for(base_value):
    """Stateless CSRF token: HMAC(secret, context string). Rotates with sessions."""
    if not base_value:
        return ""
    return hmac.new(
        _secret_key_bytes(), ("csrf:" + base_value).encode(), hashlib.sha256,
    ).hexdigest()


def csrf_token():
    """Jinja helper: the CSRF token for the current visitor (session-bound,
    falling back to the anonymous pairing cookie)."""
    session_tok = request.cookies.get(auth.SESSION_COOKIE)
    if session_tok:
        return csrf_token_for("session:" + session_tok)
    anon = request.cookies.get(ANON_CSRF_COOKIE)
    if anon:
        return csrf_token_for("anon:" + anon)
    return ""


def _csrf_ok():
    """Validate the CSRF token supplied with this POST (form field or header)."""
    expected = csrf_token()
    if not expected:
        return True  # nothing to pair against yet (see docs/SECURITY.md)
    supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
    return bool(supplied) and hmac.compare_digest(expected, supplied)


def register_routes(app):

    @app.context_processor
    def _inject_csrf():
        return {
            "csrf_token": csrf_token,
            "base_url": _public_base_url,
            "rudra_widget_enabled": _rudra_widget_enabled,
            "rudra_history": _rudra_history,
        }

    @app.after_request
    def ensure_anon_csrf_cookie(response):
        # Give anonymous visitors a pairing cookie so login/register forms
        # can carry a double-submit CSRF token.
        if (request.method == "GET" and not request.cookies.get(ANON_CSRF_COOKIE)
                and response.status_code < 400
                and "text/html" in (response.content_type or "")):
            response.set_cookie(
                ANON_CSRF_COOKIE,
                secrets.token_urlsafe(24),
                httponly=True,
                samesite="Lax",
                secure=_cookie_secure(request),
            )
        return response

    @app.before_request
    def guard_cross_origin_posts():
        if request.method != "POST":
            return None
        # Machine-authenticated pipeline triggers are exempt from browser CSRF.
        if webhook._authorized(request.headers):
            return None
        origin = request.headers.get("Origin")
        if origin:
            host = request.host
            origin_host = origin.split("://", 1)[-1].split("/", 1)[0]
            if origin_host != host:
                abort(403)
        # CSRF: authenticated requests pair against the session; anonymous
        # ones against the double-submit cookie. No cookie yet -> nothing to
        # pair, first contact is still guarded by Origin checks + rate limits.
        if not _csrf_ok():
            abort(400)
        return None

    @app.route("/")
    def index():
        items = db.list_opportunities()
        active = [o for o in items if deadlines.is_active(o)]
        fresh = sorted(
            (o for o in active if o.get("status") in ("new", "seen")),
            key=lambda o: (o.get("first_seen") or ""),
            reverse=True,
        )[:6]
        scored = helpers.score_items(active, g.user)
        matches = [
            (o, s, st, breakdown)
            for o, s, st, _reasons, _missing, breakdown in scored
            if helpers.publishable(st)
        ][:6]
        urgent = [
            o for o in active
            if helpers.deadline_soon(o) and helpers.publishable(o.get("eligibility_status"))
        ]
        urgent.sort(key=lambda o: (helpers.deadline_days(o) or 9999))
        total = len(items)
        publishable = list(helpers.PUBLISHABLE_STATUSES)
        categories = {}
        for label, slug, emoji, opp_type, q in (
            ("Internships", "internships", "💼", "internship", None),
            ("Fellowships", "fellowships", "🎓", "fellowship", None),
            ("Research", "opportunities", "🔬", "research_program", None),
            ("Scholarships", "opportunities", "🏅", "scholarship", None),
            ("Hackathons", "opportunities", "⚡", "hackathon", None),
            ("Jobs", "opportunities", "🚀", "job", None),
            ("Startups", "opportunities", "🛠️", "startup_program", None),
            ("Universities", "opportunities", "🏛️", None, "university"),
        ):
            cats = helpers.filter_items(items, query=q, opp_type=opp_type,
                                        eligibility=publishable)
            categories[label] = {
                "href": "/" + slug + (("?type=" + opp_type) if opp_type else (("?q=" + q) if q else "")),
                "count": len(cats),
                "emoji": emoji,
            }
        runs = db.list_recent_discovery_runs(limit=1)
        return render_template(
            "index.html",
            fresh=fresh,
            matches=matches,
            urgent=urgent,
            user=g.user,
            total=total,
            eligible=sum(1 for o in items if helpers.publishable(o.get("eligibility_status"))),
            verified=db.count_verifications(),
            official=sum(1 for o in items if o.get("official_url")),
            with_deadline=sum(1 for o in items if helpers.deadline_days(o) is not None),
            last_run=(runs[0].get("started_at") or "")[:16] if runs else None,
            categories=categories,
        )

    @app.route("/opportunities")
    @app.route("/internships")
    @app.route("/fellowships")
    def opportunities_list():
        kind = {"internships": "internship", "fellowships": "fellowship"}.get(
            request.path.strip("/")
        )
        type_arg = (request.args.get("type") or "").strip().lower()
        if type_arg in schema.OPPORTUNITY_TYPES:
            kind = type_arg
        status_args = request.args.getlist("status")
        if status_args and "unclear" in status_args:
            eligibility = ["unclear"]
            review = True
        else:
            eligibility = list(helpers.PUBLISHABLE_STATUSES)
            review = False
        items = helpers.filter_items(
            db.list_opportunities(),
            query=request.args.get("q"),
            opp_type=kind,
            eligibility=eligibility,
            country=request.args.get("country"),
            remote=request.args.get("remote") == "1",
            verified_only=request.args.get("verified") == "1",
        )
        sort = request.args.get("sort", "score")
        helpers.sort_items(items, sort)
        page_items, page, pages, total = helpers.paginate(items, request.args.get("page"))
        scored = helpers.score_items(page_items, g.user, by_score=(sort == "score"))
        countries = sorted({
            (o.get("country") or o.get("location") or "").strip()
            for o in db.list_opportunities()
            if (o.get("country") or o.get("location") or "").strip()
        })
        return render_template(
            "list.html",
            scored=scored,
            page=page,
            pages=pages,
            total=total,
            kind=kind,
            sort=sort,
            query=request.args.get("q", ""),
            review=review,
            user=g.user,
            schema=schema,
            countries=countries,
            country_arg=request.args.get("country", ""),
            remote_arg=request.args.get("remote") == "1",
            verified_arg=request.args.get("verified") == "1",
        )

    @app.route("/review")
    def review_queue():
        items = helpers.filter_items(
            db.list_opportunities(),
            query=request.args.get("q"),
            opp_type={"internships": "internship", "fellowships": "fellowship"}.get(
                request.args.get("type", "")
            ),
            eligibility=["unclear"],
            active_only=False,
        )
        items.sort(key=lambda o: (o.get("last_seen") or ""), reverse=True)
        scored = helpers.score_items(items, g.user, by_score=False)
        return render_template(
            "list.html",
            scored=scored,
            page=1,
            pages=1,
            total=len(items),
            kind="review",
            sort="newest",
            query=request.args.get("q", ""),
            review=True,
            schema=schema,
            user=g.user,
        )

    @app.route("/top")
    def top():
        scored = [
            pair for pair in helpers.score_items(db.list_opportunities(), g.user)
            if helpers.publishable(pair[2])
        ]
        return render_template(
            "top.html", scored=scored[:15], user=g.user,
        )

    @app.route("/urgent")
    def urgent():
        items = [
            o for o in db.list_opportunities()
            if helpers.deadline_soon(o) and helpers.publishable(o.get("eligibility_status"))
        ]
        items.sort(key=lambda o: helpers.deadline_days(o) or 9999)
        scored = helpers.score_items(items, g.user, by_score=False)
        return render_template(
            "urgent.html", scored=scored, user=g.user,
        )

    @app.route("/saved")
    @_login_required
    def saved():
        items = db.list_bookmarks(g.user["id"])
        scored = helpers.score_items(items, g.user)
        return render_template(
            "saved.html", scored=scored, user=g.user,
        )

    @app.route("/notifications", methods=["GET", "POST"])
    def notifications():
        if not g.user:
            return redirect(url_for("login", next=request.path))
        if request.method == "POST":
            ids = request.form.getlist("notification_ids")
            db.mark_user_notifications_read(
                g.user["id"], [int(i) for i in ids] if ids else None
            )
            return redirect(url_for("notifications"))
        notes = db.list_user_notifications(
            g.user["id"], include_read=True
        )
        unread = db.unread_notification_count(g.user["id"])
        return render_template(
            "notifications.html", notes=notes, unread=unread, user=g.user,
        )

    @app.route("/recently-viewed")
    def recently_viewed():
        if not g.user:
            return redirect(url_for("login", next=request.path))
        items = db.recently_viewed(g.user["id"])
        scored = helpers.score_items(items, g.user)
        return render_template(
            "saved.html", scored=scored, user=g.user, kind="recent",
        )

    @app.route("/o/<int:opportunity_id>")
    def detail(opportunity_id):
        opp = db.get_opportunity(opportunity_id)
        if not opp:
            abort(404)
        if g.user:
            db.record_view(g.user["id"], opportunity_id)
        score, status, reasons, missing, breakdown = helpers.score_item(opp, g.user)
        ai = db.get_ai_assessment(opportunity_id)
        bookmarked = bool(g.user) and db.is_bookmarked(g.user["id"], opportunity_id)
        application = (
            db.get_application(g.user["id"], opportunity_id) if g.user else None
        )
        return render_template(
            "detail.html",
            opp=opp,
            score=score,
            status=status,
            reasons=reasons,
            missing=missing,
            breakdown=breakdown,
            ai=ai,
            bookmarked=bookmarked,
            application=application,
            user=g.user,
            deadline_label=deadlines.label(deadlines.status(opp)),
            trust_score=opp.get("trust_score"),
            trust_label=trust.trust_label(opp.get("trust_score")),
        )

    @app.route("/o/<int:opportunity_id>/report", methods=["POST"])
    def report_opportunity(opportunity_id):
        if not db.get_opportunity(opportunity_id):
            abort(404)
        reason = (request.form.get("reason") or "").strip()
        if not reason:
            abort(400)
        if _report_is_blocked():
            abort(429)
        notes = (request.form.get("notes") or "").strip() or None
        db.add_report(
            opportunity_id,
            g.user["id"] if g.user else None,
            reason,
            notes,
        )
        _note_attempt(_REPORT_ATTEMPTS, request.remote_addr or "unknown")
        return redirect(request.referrer or url_for("detail", opportunity_id=opportunity_id))

    @app.route("/o/<int:opportunity_id>/save", methods=["POST"])
    @_login_required
    def save(opportunity_id):
        if db.get_opportunity(opportunity_id):
            db.add_bookmark(g.user["id"], opportunity_id)
        return redirect(request.referrer or url_for("detail", opportunity_id=opportunity_id))

    @app.route("/o/<int:opportunity_id>/unsave", methods=["POST"])
    @_login_required
    def unsave(opportunity_id):
        db.remove_bookmark(g.user["id"], opportunity_id)
        return redirect(request.referrer or url_for("detail", opportunity_id=opportunity_id))

    @app.route("/admin")
    @_admin_required
    def admin_dashboard():
        section = request.args.get("section", "overview")
        data = {"section": section}
        if section == "overview":
            data["total"] = len(db.list_opportunities())
            data["sources"] = db.count_sources()
            data["sources_enabled"] = db.count_sources(enabled_only=True)
            data["users"] = db.count_users()
            data["queue"] = db.crawl_queue_stats()
            data["reports"] = len(db.list_reports(status="pending"))
            data["runs"] = len(db.list_recent_discovery_runs(limit=5))
        elif section == "sources":
            data["sources"] = _admin_sources()
        elif section == "jobs":
            data["jobs"] = db.list_crawl_jobs(limit=100)
        elif section == "reports":
            data["reports"] = db.list_reports(status="pending")
        elif section == "users":
            data["users"] = _admin_users()
        elif section == "opportunities":
            data["items"] = db.list_opportunities()[:100]
        return render_template("admin.html", **data, user=g.user)

    @app.route("/admin/sources/<int:source_id>/toggle", methods=["POST"])
    @_admin_required
    def admin_toggle_source(source_id):
        form = request.form
        enabled = form.get("enabled") == "1"
        db.set_source_enabled(source_id, enabled)
        return redirect(url_for("admin_dashboard", section="sources"))

    @app.route("/admin/jobs/<int:job_id>/retry", methods=["POST"])
    @_admin_required
    def admin_retry_job(job_id):
        db.retry_crawl_job(job_id)
        return redirect(url_for("admin_dashboard", section="jobs"))

    @app.route("/admin/reports/<int:report_id>/resolve", methods=["POST"])
    @_admin_required
    def admin_resolve_report(report_id):
        resolution = request.form.get("resolution", "ignored")
        db.resolve_report(report_id, resolution)
        if resolution == "accepted":
            conn = db.get_connection()
            try:
                row = conn.execute(
                    "SELECT opportunity_id FROM reports WHERE id = ?", (report_id,)
                ).fetchone()
            finally:
                conn.close()
            if row:
                db.update_opportunity(row["opportunity_id"], status="closed")
        return redirect(url_for("admin_dashboard", section="reports"))

    @app.route("/admin/run", methods=["POST"])
    @_admin_required
    def admin_run():
        data = {
            "section": "overview",
            "total": len(db.list_opportunities()),
            "sources": db.count_sources(),
            "sources_enabled": db.count_sources(enabled_only=True),
            "users": db.count_users(),
            "queue": db.crawl_queue_stats(),
            "reports": len(db.list_reports(status="pending")),
            "runs": len(db.list_recent_discovery_runs(limit=5)),
        }
        try:
            data["run_summary"] = worker.run_pipeline()
        except Exception as exc:
            data["run_error"] = str(exc)[:500]
        return render_template("admin.html", **data, user=g.user)

    @app.route("/robots.txt")
    def robots():
        base = _public_base_url()
        body = (
            "User-agent: *\n"
            "Allow: /\n"
            f"Sitemap: {base}/sitemap.xml\n"
        )
        return (body, 200, {"Content-Type": "text/plain; charset=utf-8"})

    def _xml_escape(value):
        return (str(value).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))

    @app.route("/sitemap.xml")
    def sitemap():
        # Pin the base URL to the configured origin when provided: host
        # headers are client-controlled and can poison generated URLs.
        base = _public_base_url()
        static_urls = [
            (url_for("index"), "1.0", "daily"),
            (url_for("opportunities_list"), "0.9", "daily"),
            ("/internships", "0.8", "daily"),
            ("/fellowships", "0.8", "daily"),
            (url_for("top"), "0.6", "weekly"),
            (url_for("urgent"), "0.6", "daily"),
            (url_for("resources"), "0.5", "weekly"),
        ]
        entries = []
        for path, priority, freq in static_urls:
            entries.append(
                f"  <url><loc>{_xml_escape(base + path)}</loc>"
                f"<priority>{priority}</priority>"
                f"<changefreq>{freq}</changefreq></url>"
            )
        for opp in db.list_opportunities():
            if not deadlines.is_active(opp):
                continue
            loc = base + url_for("detail", opportunity_id=opp["id"])
            lastmod = (opp.get("last_seen") or opp.get("first_seen") or "")[:10]
            lastmod = lastmod if re.match(r"^\d{4}-\d{2}-\d{2}$", lastmod) else ""
            entries.append(
                f"  <url><loc>{_xml_escape(loc)}</loc>"
                f"<lastmod>{_xml_escape(lastmod)}</lastmod>"
                f"<priority>0.7</priority></url>"
            )
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "\n".join(entries)
            + "\n</urlset>\n"
        )
        return (body, 200, {"Content-Type": "application/xml; charset=utf-8"})

    @app.route("/manifest.json")
    def webmanifest():        return jsonify({
            "name": "Aawara — Internships & Fellowships for Indian students",
            "short_name": "Aawara",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#0d1117",
            "theme_color": "#5b8cff",
            "description": "Internships, fellowships, scholarships and research programs for Indian students — found 24/7 by Arjun & Vidya.",
            "icons": [],
        })

    @app.route("/sw.js")
    def service_worker():
        return Response(
            "self.addEventListener('install', () => self.skipWaiting());\n"
            "self.addEventListener('activate', (e) => e.waitUntil(clients.claim()));\n"
            "self.addEventListener('fetch', () => {});\n",
            mimetype="application/javascript",
        )

    @app.route("/resources")
    def resources():
        import json
        from pathlib import Path
        path = Path(__file__).resolve().parent.parent.parent / "config" / "curated_links.json"
        groups = json.loads(path.read_text())["groups"]
        return render_template("resources.html", groups=groups, user=g.user)

    @app.route("/stats")
    def stats():
        payload = webhook.stats_payload()
        conn = db.get_connection()
        try:
            logs = [
                dict(r) for r in conn.execute(
                    "SELECT * FROM execution_logs ORDER BY id DESC LIMIT 25"
                ).fetchall()
            ]
            runs = [
                dict(r) for r in conn.execute(
                    "SELECT scout, source_name, crawler, raw_items, stored_new, duplicates, "
                    "eligible, unclear, not_eligible, error, started_at "
                    "FROM discovery_runs ORDER BY id DESC LIMIT 20"
                ).fetchall()
            ]
            jobs = [
                dict(r) for r in conn.execute(
                    "SELECT source_name, crawler, priority, status, retry_count, "
                    "items_found, items_created, duplicates_found, error, completed_at "
                    "FROM crawl_jobs ORDER BY id DESC LIMIT 20"
                ).fetchall()
            ]
        finally:
            conn.close()
        return render_template(
            "stats.html", stats=payload, logs=logs, runs=runs, jobs=jobs,
            user=g.user,
        )

    @app.route("/resume", methods=["GET", "POST"])
    @_login_required
    def resume_page():
        from src import resume as resume_mod
        if request.method == "POST":
            sections = {}
            for key in ("education", "experience", "projects", "awards"):
                raw = request.form.get(key, "")
                rows = _json_rows(raw)
                if rows:
                    sections[key] = rows
            contact = {}
            for key in ("email", "phone", "linkedin", "github", "website"):
                value = (request.form.get(key) or "").strip()
                if value:
                    contact[key] = value
            if contact:
                sections["contact"] = contact
            db.save_user_resume(g.user["id"], sections)
            g.user = db.get_user_by_id(g.user["id"])
            return redirect(url_for("resume_page"))
        built = resume_mod.profile_resume(g.user)
        extra = db.get_user_resume(g.user["id"])
        text = resume_mod.render_text(built)
        return render_template(
            "resume.html", resume=built, text=text, extra=extra,
            user=g.user, contact=extra.get("contact") or {},
        )

    @app.route("/resume/download")
    @_login_required
    def resume_download():
        from src import resume as resume_mod
        built = resume_mod.profile_resume(g.user)
        fmt = request.args.get("fmt", "txt")
        if fmt == "pdf":
            import io
            buf = io.BytesIO()
            resume_mod.render_pdf(built, path=buf)
            return Response(
                buf.getvalue(),
                mimetype="application/pdf",
                headers={"Content-Disposition": "attachment; filename=aawara_resume.pdf"},
            )
        return Response(
            resume_mod.render_text(built),
            mimetype="text/plain",
            headers={"Content-Disposition": "attachment; filename=aawara_resume.txt"},
        )

    @app.route("/resume/tailor/<int:opportunity_id>")
    @_login_required
    def resume_tailor(opportunity_id):
        from src import resume as resume_mod
        opp = db.get_opportunity(opportunity_id)
        if not opp:
            abort(404)
        built = resume_mod.profile_resume(g.user)
        tailored, notes = resume_mod.tailor(built, opportunity=opp)
        text = resume_mod.render_text(tailored)
        return render_template(
            "tailor.html", opp=opp, text=text, notes=notes, user=g.user,
        )

    @app.route("/applications")
    @_login_required
    def applications_dashboard():
        rows = db.list_applications(g.user["id"])
        counts = {}
        for r in rows:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        urgent = [r for r in rows if helpers.deadline_soon(r) and r["status"] in ("applied", "interview")]
        return render_template(
            "applications.html", apps=rows, counts=counts, urgent=urgent,
            user=g.user,
        )

    @app.route("/opportunities/<int:opportunity_id>/apply", methods=["POST"])
    @_login_required
    def mark_applied(opportunity_id):
        db.upsert_application(
            g.user["id"], opportunity_id, status="applied",
            notes=request.form.get("notes") or None,
        )
        return redirect(request.referrer or url_for("detail", opportunity_id=opportunity_id))

    @app.route("/applications/<int:opportunity_id>/status", methods=["POST"])
    @_login_required
    def update_application_status(opportunity_id):
        status = (request.form.get("status") or "").strip()
        if status not in ("applied", "interview", "offer", "rejected", "withdrawn"):
            abort(400)
        db.upsert_application(
            g.user["id"], opportunity_id, status=status,
            notes=request.form.get("notes") or None,
        )
        return redirect(request.referrer or url_for("applications_dashboard"))

    @app.route("/applications/<int:opportunity_id>/delete", methods=["POST"])
    @_login_required
    def delete_application(opportunity_id):
        db.remove_application(g.user["id"], opportunity_id)
        return redirect(request.referrer or url_for("applications_dashboard"))

    @app.route("/api/autofill/token", methods=["GET", "POST"])
    @_login_required
    def autofill_token():
        if request.method == "POST":
            token = secrets.token_urlsafe(32)
            db.set_api_token_hash(g.user["id"], auth.hash_password(token))
            return redirect(url_for("autofill_token"))
        return render_template(
            "autofill.html", user=g.user,
            has_token=bool(db.get_api_token_hash(g.user["id"])),
        )

    @app.route("/api/autofill/resume")
    def autofill_resume():
        token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not token:
            return jsonify({"error": "missing bearer token"}), 401
        user = _user_for_api_token(token)
        if not user:
            return jsonify({"error": "invalid token"}), 401
        from src import resume as resume_mod
        built = resume_mod.profile_resume(user)
        payload = {
            "name": built.get("name"),
            "contact": built.get("contact"),
            "headline": built.get("headline"),
            "education": built.get("education"),
            "experience": built.get("experience"),
            "projects": built.get("projects"),
            "skills": built.get("skills"),
            "interests": built.get("interests"),
            "awards": built.get("awards"),
            "generated_at": db.now_iso(),
        }
        return jsonify(payload)

    @app.route("/profile", methods=["GET", "POST"])
    @_login_required
    def profile():
        if request.method == "POST":
            fields = {
                "country": request.form.get("country"),
                "citizenship": request.form.get("citizenship"),
                "degree": request.form.get("degree"),
                "degree_level": request.form.get("degree_level"),
                "current_year": _int_or_none(request.form.get("current_year")),
                "cgpa": _float_or_none(request.form.get("cgpa")),
                "university": request.form.get("university"),
                "branch": request.form.get("branch"),
                "graduation_year": _int_or_none(request.form.get("graduation_year")),
                "skills": _csv(request.form.get("skills")),
                "interests": _csv(request.form.get("interests")),
                "eligible_years": _int_list(request.form.get("eligible_years")),
            }
            db.update_user_fields(g.user["id"], {k: v for k, v in fields.items() if v is not None})
            g.user = db.get_user_by_id(g.user["id"])
        return render_template("profile.html", user=g.user)

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if g.user:
            return redirect(url_for("index"))
        error = None
        if request.method == "POST":
            if _auth_is_blocked():
                return (
                    render_template("register.html", user=g.user,
                                    error="Too many attempts. Try again in 10 minutes."),
                    429,
                )
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            confirm = request.form.get("confirm") or ""
            if len(username) < 3:
                error = "Username must be at least 3 characters."
                _auth_note_failure()
            elif username.lower() in RESERVED_USERNAMES:
                error = "That username is reserved."
                _auth_note_failure()
            elif len(password) < 8:
                error = "Password must be at least 8 characters."
                _auth_note_failure()
            elif password != confirm:
                error = "Passwords do not match."
                _auth_note_failure()
            elif db.get_user_by_username(username):
                error = "That username is already taken."
                _auth_note_failure()
            else:
                seed = store.load_profile()
                user_id = db.create_user(
                    username, auth.hash_password(password), profile=seed or {}
                )
                return _set_session_cookie(
                    redirect(url_for("index")), auth.start_session(user_id)
                )
        return render_template("register.html", user=g.user, error=error,
                               google_configured=_auth_provider_configured("google"),
                               github_configured=_auth_provider_configured("github"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.user:
            return redirect(url_for("index"))
        error = None
        if request.method == "POST":
            if _auth_is_blocked():
                return (
                    render_template("login.html", user=g.user,
                                    error="Too many attempts. Try again in 10 minutes."),
                    429,
                )
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            user = db.get_user_by_username(username)
            if user and auth.verify_password(password, user.get("password_hash")):
                response = redirect(_safe_next(request.args.get("next")) or url_for("index"))
                return _set_session_cookie(response, auth.start_session(user["id"]))
            _auth_note_failure()
            error = "Invalid username or password."
        return render_template("login.html", user=g.user, error=error,
                               google_configured=_auth_provider_configured("google"),
                               github_configured=_auth_provider_configured("github"))

    @app.route("/logout", methods=["POST"])
    def logout():
        auth.end_session(request.cookies.get(auth.SESSION_COOKIE))
        response = redirect(url_for("index"))
        response.delete_cookie(auth.SESSION_COOKIE)
        return response

    @app.route("/auth/<provider>")
    def oauth_start(provider):
        if provider not in ("google", "github"):
            abort(404)
        try:
            state = oauth.new_state()
            response = redirect(
                oauth.google_auth_url(state) if provider == "google" else oauth.github_auth_url(state)
            )
        except oauth.OAuthError as exc:
            return render_template(
                "oauth.html", user=g.user,
                error=f"{provider.title()} login isn't configured on this "
                      f"server yet ({exc}). Use email login instead, or ask "
                      f"the site owner to add the provider keys.",
            ), 200
        response.set_cookie(
            oauth.STATE_COOKIE, state,
            httponly=True,
            samesite="Lax",
            max_age=600,
            secure=_cookie_secure(request),
        )
        return response

    @app.route("/auth/<provider>/callback")
    def oauth_callback(provider):
        if provider not in ("google", "github"):
            abort(404)
        stored_state = request.cookies.get(oauth.STATE_COOKIE)
        if not stored_state or stored_state != request.args.get("state"):
            return render_template("oauth.html", user=g.user, error="Invalid OAuth state."), 400
        response = redirect(url_for("index"))
        response.delete_cookie(oauth.STATE_COOKIE)
        code = request.args.get("code")
        if not code:
            return render_template("oauth.html", user=g.user, error="OAuth login cancelled or denied."), 400
        try:
            profile = (
                oauth.google_exchange(code) if provider == "google" else oauth.github_exchange(code)
            )
            user_id = oauth.find_or_create_user(profile)
        except oauth.OAuthError as exc:
            return render_template("oauth.html", user=g.user, error=f"OAuth failed: {exc}"), 400
        except Exception as exc:
            return render_template("oauth.html", user=g.user, error=f"OAuth failed: {exc}"), 500
        return _set_session_cookie(response, auth.start_session(user_id))

    @app.route("/rudra", methods=["GET"])
    @_login_required
    def rudra():
        history = db.get_chat_history(g.user["id"])
        return render_template("rudra.html", history=history, user=g.user)

    @app.route("/rudra/send", methods=["POST"])
    @_login_required
    def rudra_send():
        message = (request.form.get("message") or "").strip()
        if not message:
            return redirect(url_for("rudra"))
        db.add_chat_message(g.user["id"], "user", message[:4000])
        history = db.get_chat_history(g.user["id"], limit=20)
        reply, provider = ai.chat_ask(
            [{"role": r["role"], "content": r["content"]} for r in history],
            profile=ai.safe_profile(g.user),
        )
        if reply:
            db.add_chat_message(g.user["id"], "assistant", reply[:4000], provider)
        else:
            configured = ai.configured_providers()
            if configured:
                detail = "The configured AI service is not responding (check the logs / API quota)."
            else:
                detail = ("No AI provider is configured on this server "
                          "(add GEMINI_API_KEY or OPENAI_API_KEY).")
            db.add_chat_message(
                g.user["id"], "assistant",
                "Rudra is offline right now. " + detail,
            )
        return redirect(url_for("rudra"))

    @app.route("/rudra/stream", methods=["POST"])
    @_login_required
    def rudra_stream():
        """SSE streaming endpoint: Rudra replies token-by-token so the first
        text appears immediately instead of after a long silent wait."""
        message = (request.form.get("message") or "").strip()
        if not message:
            return redirect(url_for("rudra"))
        db.add_chat_message(g.user["id"], "user", message[:4000])
        history = db.get_chat_history(g.user["id"], limit=12)
        user_id = g.user["id"]
        profile = ai.safe_profile(g.user)
        messages = (
            [{"role": "system", "content": ai.RUDRA_SYSTEM_PROMPT}]
            + [{"role": "system", "content": "STUDENT PROFILE (use for personalization, keep facts locked):\n" + json.dumps(profile, ensure_ascii=False)}]
            + [{"role": r["role"], "content": r["content"]} for r in history]
        )

        def generate():
            collected = []
            try:
                for fragment in ai.gemini_stream(messages):
                    collected.append(fragment)
                    yield f"data: {fragment}\n\n"
            except Exception:
                pass
            reply = "".join(collected).strip()
            if reply:
                db.add_chat_message(user_id, "assistant", reply[:4000], "gemini")
                yield f"data: __DONE__:{reply}\n\n"
            else:
                fallback = ("Rudra is offline right now — neither the local "
                            "model nor an API key is reachable. Try again in a moment.")
                db.add_chat_message(user_id, "assistant", fallback)
                yield f"data: __DONE__:{fallback}\n\n"

        from flask import Response as FlaskResponse
        return FlaskResponse(
            generate(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.route("/rudra/clear", methods=["POST"])
    @_login_required
    def rudra_clear():
        db.clear_chat_history(g.user["id"])
        return redirect(url_for("rudra"))

    # --- Rudra floating widget API (authenticated JSON / SSE) ---

    @app.route("/rudra/api/chat", methods=["POST"])
    @_login_required_json
    def rudra_api_chat():
        payload = request.get_json(silent=True) or {}
        message = str(payload.get("message") or "").strip()
        if not message:
            return jsonify({"error": "empty message"}), 400
        key = f"{g.user['id']}:{request.remote_addr or 'unknown'}"
        if _throttled(_RUDRA_ATTEMPTS, key, _RUDRA_MAX_MESSAGES,
                      _RUDRA_WINDOW_SECONDS):
            return jsonify({"error": "Too many messages — please wait a moment."}), 429
        _note_attempt(_RUDRA_ATTEMPTS, key)

        from src.rudra import orchestrator as rudra_orchestrator
        hint = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        conversation_id = payload.get("conversation_id") or None
        try:
            turn = rudra_orchestrator.prepare_turn(
                g.user, message[:4000], hint, conversation_id)
        except Exception:
            app.logger.exception("rudra turn preparation failed")
            return jsonify({"error": "Could not start the chat turn. Try again."}), 500

        if payload.get("stream") is False:
            try:
                reply, provider = rudra_orchestrator.complete_reply(turn, g.user)
            except Exception:
                app.logger.exception("rudra reply failed")
                reply, provider = None, None
            if not reply:
                return jsonify({"error": "Rudra is offline right now — try again shortly."}), 503
            return jsonify({
                "reply": reply[:4000],
                "provider": provider,
                "conversation_id": turn["conversation_id"],
                "tools_used": turn["tools_used"],
                "sources": rudra_orchestrator._sources_for(turn),
            })

        # Bind everything the generator needs BEFORE streaming starts:
        # request/app-local proxies are not available mid-stream.
        user = g.user
        conversation_id_out = turn["conversation_id"]
        tools_used = turn["tools_used"]

        def generate():
            try:
                yield "data: %s\n\n" % json.dumps({
                    "type": "start",
                    "conversation_id": conversation_id_out,
                    "tools_used": tools_used,
                }, ensure_ascii=False)
                for event in rudra_orchestrator.stream_reply(turn, user):
                    yield "data: %s\n\n" % json.dumps(event, ensure_ascii=False)
            except Exception:
                # A crashed generator must still tell the client something.
                app.logger.exception("rudra stream crashed")
                yield "data: %s\n\n" % json.dumps(
                    {"type": "error", "error": "Unexpected error — please retry."})

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache",
                     "X-Accel-Buffering": "no"},
        )

    @app.route("/rudra/api/new-chat", methods=["POST"])
    @_login_required_json
    def rudra_api_new_chat():
        import uuid as _uuid
        conversation_id = _uuid.uuid4().hex[:16]
        return jsonify({"conversation_id": conversation_id, "messages": []})

    @app.route("/rudra/api/clear", methods=["POST"])
    @_login_required_json
    def rudra_api_clear():
        payload = request.get_json(silent=True) or {}
        conversation_id = payload.get("conversation_id")
        deleted = None
        if conversation_id:
            deleted = db.delete_conversation(g.user["id"], conversation_id)
            remaining = db.get_chat_history(g.user["id"], limit=1)
            new_conversation_id = (remaining[0].get("conversation_id")
                                   if remaining else None)
        else:
            db.clear_chat_history(g.user["id"])
            new_conversation_id = None
        return jsonify({"ok": True, "deleted": deleted,
                        "conversation_id": new_conversation_id})

    @app.route("/rudra/api/feedback", methods=["POST"])
    @_login_required_json
    def rudra_api_feedback():
        payload = request.get_json(silent=True) or {}
        feedback = payload.get("feedback")
        if feedback not in ("up", "down", None):
            return jsonify({"error": "feedback must be up|down|null"}), 400
        changed = db.set_message_feedback(
            g.user["id"], payload.get("message_id"), feedback)
        if not changed:
            return jsonify({"error": "message not found"}), 404
        return jsonify({"ok": True})

    @app.route("/rudra/api/suggestions")
    @_login_required_json
    def rudra_api_suggestions():
        if os.environ.get("RUDRA_SUGGESTIONS_ENABLED", "true").strip().lower() \
                in ("0", "false"):
            return jsonify({"suggestions": []})
        from src.rudra.context import build_suggestions
        try:
            suggestions = build_suggestions(g.user)
        except Exception:
            app.logger.exception("rudra suggestion build failed")
            suggestions = []
        return jsonify({"suggestions": suggestions})

    @app.route("/run", methods=["POST"])
    def run_pipeline():
        if not webhook._authorized(request.headers):
            return {"error": "unauthorized"}, 401
        try:
            summary = worker.run_pipeline()
            return summary
        except Exception:
            # Never leak internal error details to callers.
            return {"error": "pipeline run failed"}, 500

    @app.route("/health")
    def health():
        return {"ok": True}

    # --- AAWARA Agent Dashboard ---

    @app.route("/agents")
    def agents_dashboard():
        from src.agents.orchestrator import get_orchestrator, init_orchestrator
        orch = get_orchestrator()
        if not orch.get_all_agents():
            orch = init_orchestrator()
        agents = [a.to_dict() for a in orch.get_all_agents()]

        # Get real metrics from database
        conn = db.get_connection()
        try:
            agent_task_counts = {}
            rows = conn.execute(
                "SELECT agent_id, status, COUNT(*) as cnt FROM agent_tasks "
                "GROUP BY agent_id, status"
            ).fetchall()
            for r in rows:
                aid = r["agent_id"]
                if aid not in agent_task_counts:
                    agent_task_counts[aid] = {}
                agent_task_counts[aid][r["status"]] = r["cnt"]

            agent_event_counts = {}
            rows = conn.execute(
                "SELECT agent_id, COUNT(*) as cnt FROM agent_events "
                "GROUP BY agent_id"
            ).fetchall()
            for r in rows:
                agent_event_counts[r["agent_id"]] = r["cnt"]

            recent_events = conn.execute(
                "SELECT * FROM agent_events ORDER BY id DESC LIMIT 12"
            ).fetchall()

            task_stats = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM agent_tasks GROUP BY status"
            ).fetchall()
            task_summary = {r["status"]: r["cnt"] for r in task_stats}
        finally:
            conn.close()

        for agent in agents:
            aid = agent["agent_id"]
            agent["task_counts"] = agent_task_counts.get(aid, {})
            agent["event_count"] = agent_event_counts.get(aid, 0)

        return render_template(
            "agents.html",
            agents=agents,
            recent_events=[dict(r) for r in recent_events],
            task_summary=task_summary,
            user=g.user,
        )

    @app.route("/agents/<agent_id>")
    def agent_detail_page(agent_id):
        from src.agents.orchestrator import get_orchestrator
        orch = get_orchestrator()
        agent = orch.get_agent(agent_id)
        if not agent:
            abort(404)

        conn = db.get_connection()
        try:
            recent_tasks = conn.execute(
                "SELECT * FROM agent_tasks WHERE agent_id = ? ORDER BY id DESC LIMIT 30",
                (agent_id,),
            ).fetchall()
            recent_events = conn.execute(
                "SELECT * FROM agent_events WHERE agent_id = ? ORDER BY id DESC LIMIT 30",
                (agent_id,),
            ).fetchall()
            task_stats = conn.execute(
                "SELECT status, COUNT(*) as cnt, AVG(duration_ms) as avg_duration "
                "FROM agent_tasks WHERE agent_id = ? GROUP BY status",
                (agent_id,),
            ).fetchall()
        finally:
            conn.close()

        return render_template(
            "agent_detail.html",
            agent=agent.to_dict(),
            tasks=[dict(r) for r in recent_tasks],
            events=[dict(r) for r in recent_events],
            task_stats=[dict(r) for r in task_stats],
            user=g.user,
        )

    @app.route("/agents/<agent_id>/run", methods=["POST"])
    @_admin_required
    def agent_run(agent_id):
        from src.agents.orchestrator import get_orchestrator
        orch = get_orchestrator()
        result = orch.run_agent(agent_id, {})
        return redirect(url_for("agent_detail_page", agent_id=agent_id))

    @app.route("/stats.json")
    def stats_json():
        if not webhook._authorized(request.headers):
            return {"error": "unauthorized"}, 401
        return webhook.stats_payload()

    @app.errorhandler(404)
    def not_found(_exc):
        return render_template("404.html", user=g.user), 404


def _int_or_none(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _csv(value):
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def _int_list(value):
    values = []
    for part in (value or "").split(","):
        part = part.strip()
        if part.isdigit():
            values.append(int(part))
    return values


def _json_rows(value):
    import json
    if not (value or "").strip():
        return []
    try:
        rows = json.loads(value)
    except ValueError:
        return []
    if not isinstance(rows, list):
        return []
    cleaned = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        cleaned.append({k: str(v).strip() for k, v in row.items() if str(v).strip()})
    return cleaned


def _user_for_api_token(token):
    for row in db.get_users_with_tokens():
        stored = row["api_token_hash"]
        if stored and auth.verify_password(token, stored):
            return db.get_user_by_id(row["id"])
    return None
