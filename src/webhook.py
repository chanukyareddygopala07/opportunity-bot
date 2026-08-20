"""Phase 13 — local webhook so n8n can trigger the pipeline on a schedule.

Endpoints:
  GET  /health          -> 200 {"ok": true}
  POST /run             -> runs the full pipeline; X-Run-Token header required

The token comes from the RUN_TOKEN environment variable.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from src import worker

RUN_PATH = "/run"
HEALTH_PATH = "/health"
STATS_PATH = "/stats"


def _authorized(headers):
    expected = os.environ.get("RUN_TOKEN", "")
    if not expected:
        return False
    return headers.get("X-Run-Token") == expected


def stats_payload():
    from src import db
    conn = db.get_connection()
    try:
        counts = {}
        for name in ("opportunities", "users", "sources", "notifications",
                     "execution_logs", "verifications", "ai_assessments"):
            counts[name] = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        counts["opportunities"] = conn.execute(
            "SELECT COUNT(*) FROM opportunities"
        ).fetchone()[0]
        counts["duplicates"] = conn.execute(
            "SELECT COUNT(*) FROM opportunities WHERE duplicate_of IS NOT NULL"
        ).fetchone()[0]
        counts["verified"] = conn.execute(
            "SELECT COUNT(*) FROM opportunities WHERE verification_status = 'verified'"
        ).fetchone()[0]
        counts["saved"] = conn.execute(
            "SELECT COUNT(*) FROM opportunities WHERE saved = 1"
        ).fetchone()[0]
        last = conn.execute(
            "SELECT started_at, message FROM execution_logs "
            "WHERE workflow = 'worker' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return {
            "counts": counts,
            "last_pipeline": dict(last) if last else None,
        }
    finally:
        conn.close()


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == HEALTH_PATH:
            self._send_json(200, {"ok": True})
        elif self.path == STATS_PATH:
            if not _authorized(self.headers):
                return self._send_json(401, {"error": "unauthorized"})
            self._send_json(200, stats_payload())
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != RUN_PATH:
            return self._send_json(404, {"error": "not found"})
        if not _authorized(self.headers):
            return self._send_json(401, {"error": "unauthorized"})
        try:
            summary = worker.run_pipeline()
            self._send_json(200, summary)
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def log_message(self, *args):
        pass


def make_server(host="0.0.0.0", port=8080):
    return ThreadingHTTPServer((host, port), Handler)


def serve(host="0.0.0.0", port=8080):
    server = make_server(host, port)
    server.serve_forever()


if __name__ == "__main__":
    serve()
    raise SystemExit(0)