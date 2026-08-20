"""Web app routes: pages for browsing, auth, profile, stats, pipeline trigger."""
import hmac
import json
import os
import secrets

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
        admin_username = os.environ.get("ADMIN_USERNAME", "admin")
        if not g.user or g.user.get("username") != admin_username:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    wrapped.__name__ = view.__name__
    return wrapped


def _set_session_cookie(response, token):
    response.set_cookie(
        auth.SESSION_COOKIE,
        token,
        max_age=auth.SESSION_DAYS * 24 * 3600,
        httponly=True,
        samesite="Lax",
    )
    return response


def register_routes(app):

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

    @app.route("/o/<int:opportunity_id>")
    def detail(opportunity_id):
        opp = db.get_opportunity(opportunity_id)
        if not opp:
            abort(404)
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
        notes = (request.form.get("notes") or "").strip() or None
        db.add_report(
            opportunity_id,
            g.user["id"] if g.user else None,
            reason,
            notes,
        )
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
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            confirm = request.form.get("confirm") or ""
            if len(username) < 3:
                error = "Username must be at least 3 characters."
            elif len(password) < 8:
                error = "Password must be at least 8 characters."
            elif password != confirm:
                error = "Passwords do not match."
            elif db.get_user_by_username(username):
                error = "That username is already taken."
            else:
                seed = store.load_profile()
                user_id = db.create_user(
                    username, auth.hash_password(password), profile=seed or {}
                )
                return _set_session_cookie(
                    redirect(url_for("index")), auth.start_session(user_id)
                )
        return render_template("register.html", user=g.user, error=error)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.user:
            return redirect(url_for("index"))
        error = None
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            user = db.get_user_by_username(username)
            if user and auth.verify_password(password, user.get("password_hash")):
                response = redirect(_safe_next(request.args.get("next")) or url_for("index"))
                return _set_session_cookie(response, auth.start_session(user["id"]))
            error = "Invalid username or password."
        return render_template("login.html", user=g.user, error=error)

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
        state = oauth.new_state()
        response = redirect(
            oauth.google_auth_url(state) if provider == "google" else oauth.github_auth_url(state)
        )
        response.set_cookie(oauth.STATE_COOKIE, state, httponly=True, samesite="Lax")
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
            profile=g.user,
        )
        if reply:
            db.add_chat_message(g.user["id"], "assistant", reply[:4000], provider)
        else:
            db.add_chat_message(
                g.user["id"], "assistant",
                "Rudra is offline right now — neither the local model nor an "
                "API key is reachable. Try again in a moment.",
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
        profile = {k: v for k, v in g.user.items() if k not in ("password_hash", "api_token_hash")}
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

    @app.route("/run", methods=["POST"])
    def run_pipeline():
        if not webhook._authorized(request.headers):
            return {"error": "unauthorized"}, 401
        try:
            summary = worker.run_pipeline()
            return summary
        except Exception as exc:
            return {"error": str(exc)}, 500

    @app.route("/health")
    def health():
        return {"ok": True}

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
