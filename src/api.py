"""Phase H — JSON REST API (FastAPI, port 8000).

Read-mostly public API over the same SQLite store the web UI uses.
Public: opportunity browse/search, types, enabled source list.
Token-gated (X-Run-Token): crawl jobs, stats, agent introspection and
execution — internal pipeline infrastructure never exposed anonymously.
Run:  uvicorn src.api:app --port 8000   (or  python -m src.api)
"""
import hmac
import os
import time
import uuid
from datetime import datetime, timezone

from src import db, deadlines, trust, schema
from src.envfile import load_dotenv
from src.webhook import _authorized
from src.webapp import helpers

load_dotenv()

try:
    from fastapi import FastAPI, HTTPException, Query, Request
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel, Field
except ImportError:
    FastAPI = None


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=200)
    type: str | None = None
    country: str | None = None
    remote: bool | None = None
    verified_only: bool | None = None
    limit: int = Field(20, ge=1, le=100)


# --- Anonymous abuse-report rate limiting (in-process; per-IP token bucket) ---
_REPORT_ATTEMPTS: dict[str, list[float]] = {}
_REPORT_MAX = 5
_REPORT_WINDOW_SECONDS = 3600

# --- Global per-IP request throttle ---
_API_ATTEMPTS: dict[str, list[float]] = {}
_API_MAX_REQUESTS = 120
_API_WINDOW_SECONDS = 60


def _rate_limited(key, store_, max_requests, window_seconds):
    now = time.time()
    window = [t for t in store_.get(key, []) if now - t < window_seconds]
    store_[key] = window
    if len(window) >= max_requests:
        return True
    store_[key].append(now)
    return False


def _serialize(opp, user=None):
    days = deadlines.days_left(opp.get("deadline"))
    return {
        "id": opp["id"],
        "title": opp.get("title"),
        "organization": opp.get("organization"),
        "type": opp.get("type"),
        "category": opp.get("category"),
        "country": opp.get("country"),
        "location": opp.get("location"),
        "remote": bool(opp.get("remote")),
        "deadline": opp.get("deadline"),
        "deadline_status": deadlines.label(deadlines.status(opp)),
        "deadline_days_left": days,
        "application_url": opp.get("application_url"),
        "official_url": opp.get("official_url"),
        "source_url": opp.get("source_url"),
        "eligibility_status": opp.get("eligibility_status"),
        "match_score": opp.get("match_score"),
        "trust_score": opp.get("trust_score"),
        "trust_label": trust.trust_label(opp.get("trust_score")),
        "stipend": opp.get("stipend"),
        "funding": opp.get("funding"),
        "first_seen": opp.get("first_seen"),
    }


def _filtered(items, type_arg=None, country=None, remote=None,
              verified_only=None, query=None):
    return helpers.filter_items(
        items,
        query=query,
        opp_type=type_arg,
        country=country,
        remote=remote,
        verified_only=verified_only,
    )


def create_app():
    if FastAPI is None:
        raise RuntimeError("fastapi is not installed; pip install fastapi uvicorn")

    app = FastAPI(
        title="AAWARA API",
        description="Opportunity discovery for Indian students — Arjun & Vidya.",
        version="1.0.0",
    )

    @app.middleware("http")
    async def throttle(request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        if _rate_limited(client_ip, _API_ATTEMPTS,
                         _API_MAX_REQUESTS, _API_WINDOW_SECONDS):
            return JSONResponse(
                {"error": "rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(_API_WINDOW_SECONDS)},
            )
        return await call_next(request)

    @app.get("/health")
    def health():
        return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}

    @app.get("/opportunities")
    def opportunities(
        q: str | None = Query(None, max_length=200),
        type: str | None = None,
        country: str | None = None,
        remote: bool | None = None,
        verified_only: bool | None = None,
        sort: str = Query("score", pattern="^(score|deadline|newest)$"),
        limit: int = Query(20, ge=1, le=100),
    ):
        items = _filtered(
            db.list_opportunities(), type, country, remote, verified_only, q
        )
        if sort == "deadline":
            items.sort(key=lambda o: deadlines.days_left(o.get("deadline")) or 9999)
        elif sort == "newest":
            items.sort(key=lambda o: o.get("first_seen") or "", reverse=True)
        return {
            "total": len(items),
            "items": [_serialize(o) for o in items[:limit]],
        }

    @app.get("/opportunities/{opportunity_id}")
    def opportunity_detail(opportunity_id: int):
        opp = db.get_opportunity(opportunity_id)
        if not opp:
            raise HTTPException(404, "opportunity not found")
        return _serialize(opp)

    @app.post("/opportunities/search")
    def search(body: SearchRequest):
        items = _filtered(
            db.list_opportunities(), body.type, body.country, body.remote,
            body.verified_only, body.query,
        )
        items.sort(key=lambda o: o.get("match_score") or 0, reverse=True)
        return {
            "query": body.query,
            "total": len(items),
            "items": [_serialize(o) for o in items[: body.limit]],
        }

    @app.get("/types")
    def types():
        return {"types": [t for t in schema.OPPORTUNITY_TYPES]}

    @app.get("/sources")
    def sources():
        from src import sources as registry
        registry.sync_sources()
        rows = registry.list_enabled_sources()
        return {
            "total": len(rows),
            "items": [{
                "id": s.get("id"), "name": s.get("name"),
                "url": s.get("url"), "method": s.get("method"),
                "category": s.get("category"), "priority": s.get("priority"),
            } for s in rows],
        }

    @app.get("/crawl/jobs")
    def crawl_jobs(request: Request, status: str | None = None,
                   limit: int = Query(50, le=200)):
        if not _authorized(request.headers):
            raise HTTPException(401, "unauthorized")
        jobs = db.list_crawl_jobs(limit=limit, status=status)
        return {"total": len(jobs), "items": jobs}

    @app.get("/stats")
    def stats(request: Request):
        if not _authorized(request.headers):
            raise HTTPException(401, "unauthorized")
        payload = None
        from src import webhook
        payload = webhook.stats_payload()
        payload["deadline_statuses"] = {}
        payload["queue"] = db.crawl_queue_stats()
        payload["reports_pending"] = len(db.list_reports())
        return payload

    @app.post("/report/{opportunity_id}")
    def report(opportunity_id: int, request: Request, reason: str,
               notes: str | None = None):
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        window = [t for t in _REPORT_ATTEMPTS.get(client_ip, [])
                  if now - t < _REPORT_WINDOW_SECONDS]
        if len(window) >= _REPORT_MAX:
            raise HTTPException(429, "too many reports; try again later")
        if not db.get_opportunity(opportunity_id):
            raise HTTPException(404, "opportunity not found")
        report_id = db.add_report(opportunity_id, None, reason, notes)
        window.append(now)
        _REPORT_ATTEMPTS[client_ip] = window
        return {"ok": True, "report_id": report_id}

    @app.post("/crawl")
    def trigger_crawl(request: Request):
        token = request.headers.get("X-Run-Token") or ""
        expected = os.environ.get("RUN_TOKEN")
        if not expected or not hmac.compare_digest(
                token.encode(), expected.encode()):
            raise HTTPException(403, "invalid run token")
        from src import worker
        summary = worker.run_pipeline()
        return {"ok": True, "summary": summary}

    # --- AAWARA Agent System endpoints (token-gated: internal infrastructure) ---

    @app.get("/api/agents")
    def list_agents(request: Request):
        if not _authorized(request.headers):
            raise HTTPException(401, "unauthorized")
        from src.agents.orchestrator import get_orchestrator
        orch = get_orchestrator()
        if not orch.get_all_agents():
            from src.agents.orchestrator import init_orchestrator
            orch = init_orchestrator()
        return {
            "success": True,
            "data": [a.to_dict() for a in orch.get_all_agents()],
        }

    @app.get("/api/agents/{agent_id}")
    def agent_detail(agent_id: str, request: Request):
        if not _authorized(request.headers):
            raise HTTPException(401, "unauthorized")
        from src.agents.orchestrator import get_orchestrator
        orch = get_orchestrator()
        agent = orch.get_agent(agent_id)
        if not agent:
            raise HTTPException(404, f"Agent {agent_id} not found")
        conn = db.get_connection()
        try:
            recent_tasks = conn.execute(
                "SELECT * FROM agent_tasks WHERE agent_id = ? ORDER BY id DESC LIMIT 20",
                (agent_id,),
            ).fetchall()
            recent_events = conn.execute(
                "SELECT * FROM agent_events WHERE agent_id = ? ORDER BY id DESC LIMIT 20",
                (agent_id,),
            ).fetchall()
        finally:
            conn.close()
        return {
            "success": True,
            "data": {
                "agent": agent.to_dict(),
                "recent_tasks": [dict(r) for r in recent_tasks],
                "recent_events": [dict(r) for r in recent_events],
            },
        }

    @app.get("/api/agent-tasks")
    def list_agent_tasks(
        request: Request,
        agent_id: str | None = None,
        status: str | None = None,
        limit: int = Query(50, le=200),
    ):
        if not _authorized(request.headers):
            raise HTTPException(401, "unauthorized")
        conn = db.get_connection()
        try:
            sql = "SELECT * FROM agent_tasks"
            params = []
            if agent_id:
                sql += " WHERE agent_id = ?"
                params.append(agent_id)
            if status:
                sql += " AND status = ?" if params else " WHERE status = ?"
                params.append(status)
            sql += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        return {"success": True, "data": [dict(r) for r in rows]}

    @app.get("/api/agent-events")
    def list_agent_events(
        request: Request,
        agent_id: str | None = None,
        event_type: str | None = None,
        limit: int = Query(50, le=200),
    ):
        if not _authorized(request.headers):
            raise HTTPException(401, "unauthorized")
        conn = db.get_connection()
        try:
            sql = "SELECT * FROM agent_events"
            params = []
            if agent_id:
                sql += " WHERE agent_id = ?"
                params.append(agent_id)
            if event_type:
                sql += " AND event_type = ?" if params else " WHERE event_type = ?"
                params.append(event_type)
            sql += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        return {"success": True, "data": [dict(r) for r in rows]}

    @app.post("/api/agents/{agent_id}/run")
    def run_agent(agent_id: str, request: Request):
        if not _authorized(request.headers):
            raise HTTPException(401, "unauthorized")
        from src.agents.orchestrator import get_orchestrator
        orch = get_orchestrator()
        result = orch.run_agent(agent_id, {})
        return {"success": True, "data": result.to_dict()}

    @app.get("/api/pipeline/status")
    def pipeline_status(request: Request):
        if not _authorized(request.headers):
            raise HTTPException(401, "unauthorized")
        from src.agents.orchestrator import get_orchestrator
        orch = get_orchestrator()
        return {"success": True, "data": orch.get_pipeline_status()}

    return app


app = create_app() if FastAPI is not None else None


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.api:app", host="0.0.0.0", port=8000)