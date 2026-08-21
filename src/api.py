"""Phase H — JSON REST API (FastAPI, port 8000).

Read-mostly public API over the same SQLite store the web UI uses.
Run:  uvicorn src.api:app --port 8000   (or  python -m src.api)
"""
import os
import uuid
from datetime import datetime, timezone

from src import db, deadlines, trust, schema
from src.envfile import load_dotenv
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
    def crawl_jobs(status: str | None = None, limit: int = Query(50, le=200)):
        jobs = db.list_crawl_jobs(limit=limit, status=status)
        return {"total": len(jobs), "items": jobs}

    @app.get("/stats")
    def stats():
        payload = None
        from src import webhook
        payload = webhook.stats_payload()
        payload["deadline_statuses"] = {}
        payload["queue"] = db.crawl_queue_stats()
        payload["reports_pending"] = len(db.list_reports())
        return payload

    @app.post("/report/{opportunity_id}")
    def report(opportunity_id: int, reason: str, notes: str | None = None):
        if not db.get_opportunity(opportunity_id):
            raise HTTPException(404, "opportunity not found")
        db.add_report(opportunity_id, None, reason, notes)
        return {"ok": True, "report_id": opportunity_id}

    @app.post("/crawl")
    def trigger_crawl(request: Request):
        token = request.headers.get("X-Run-Token") or ""
        expected = os.environ.get("RUN_TOKEN")
        if not expected or token != expected:
            raise HTTPException(403, "invalid run token")
        from src import worker
        summary = worker.run_pipeline()
        return {"ok": True, "summary": summary}

    # --- AAWARA Agent System endpoints ---

    @app.get("/api/agents")
    def list_agents():
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
    def agent_detail(agent_id: str):
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
        agent_id: str | None = None,
        status: str | None = None,
        limit: int = Query(50, le=200),
    ):
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
        agent_id: str | None = None,
        event_type: str | None = None,
        limit: int = Query(50, le=200),
    ):
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
    def run_agent(agent_id: str):
        from src.agents.orchestrator import get_orchestrator
        orch = get_orchestrator()
        result = orch.run_agent(agent_id, {})
        return {"success": True, "data": result.to_dict()}

    @app.get("/api/pipeline/status")
    def pipeline_status():
        from src.agents.orchestrator import get_orchestrator
        orch = get_orchestrator()
        return {"success": True, "data": orch.get_pipeline_status()}

    return app


app = create_app() if FastAPI is not None else None


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.api:app", host="0.0.0.0", port=8000)