# Deploying AAWARA

## Current production deployment (this machine, via Docker Compose)

The app runs on this machine with Docker Compose from this repository:

```bash
docker compose up -d --build
```

| Service | Container | URL | Notes |
|---|---|---|---|
| Web (Flask + waitress) | `opportunity-web` | http://127.0.0.1:8080 | main app, bound to localhost |
| API (FastAPI + uvicorn) | `opportunity-api` | http://127.0.0.1:8000 | token-gated internals |
| Scheduler (n8n) | `opportunity-n8n` | http://127.0.0.1:5678 | cron triggers `/run` twice daily |

Data persists in `./data/opportunity.db` (bind mount). The web container runs
as a non-root user under **waitress** (production WSGI server).

### Required environment (.env — never commit)

```text
RUN_TOKEN=<openssl rand -hex 16>          # pipeline trigger + admin API
SESSION_SECRET=<openssl rand -hex 32>     # cookie signing
N8N_BASIC_AUTH_USER=admin
N8N_BASIC_AUTH_PASSWORD=<random>          # local n8n editor login
GROQ_API_KEY=<groq console key>           # Rudra's primary LLM provider
GROQ_MODEL=openai/gpt-oss-120b
ADMIN_USERNAME=                           # see "Gaining admin" below
PUBLIC_BASE_URL=http://localhost:8080     # set to the real origin in prod
COOKIE_SECURE=auto                        # auto = Secure when HTTPS detected
```

`docker compose config --quiet` validates before deploying; missing required
values fail fast (`:?` guards) instead of booting an insecure stack.

### Gaining admin

Admin rights come from the `users.role` column only. Register your account
first, then set `ADMIN_USERNAME=<your-username>` in `.env` and restart
(`docker compose up -d web`) — startup promotes that existing user.

### Operations

```bash
docker compose logs -f web          # tail logs
docker compose restart web          # restart after .env change
docker compose up -d --build        # redeploy new code
sqlite3 data/opportunity.db         # inspect the store (stop writes first)
```

Health checks: `GET /health` on both web (:8080) and api (:8000).
Token-protected ops: `GET /stats.json`, `POST /run`, `GET /crawl/jobs`.

## Render (auto-deploy from GitHub)

The repo root Dockerfile is Render-ready (self-contained image; Render builds
it and routes HTTPS). The push of `main` triggers their pipeline if connected.

Render service settings:

1. **Type:** Web Service → Docker
2. **Health check path:** `/health`
3. **Environment variables** (set in the Render dashboard, not committed):
   - `RUN_TOKEN`, `SESSION_SECRET` (generate fresh values)
   - `GROQ_API_KEY`, `GROQ_MODEL=openai/gpt-oss-120b`
   - `PUBLIC_BASE_URL=https://<your-service>.onrender.com`
   - `COOKIE_SECURE=force` (TLS terminates at Render)
   - optional: `OPENAI_API_KEY` / `GEMINI_API_KEY` / `OLLAMA_URL`,
     `TELEGRAM_BOT_TOKEN`, `ADMIN_USERNAME`
4. **Disk:** attach a persistent disk mounted at `/app/data` — otherwise the
   SQLite file resets on every deploy.
5. The n8n scheduler is NOT part of a Render web service; either run n8n
   separately or replace it with a Render Cron Job hitting
   `POST https://<service>/run` with header `X-Run-Token: $RUN_TOKEN`.

## CI gate

Every push runs GitHub Actions (`.github/workflows/ci.yml`): ruff lint,
full pytest suite, bandit security scan, and app-factory smoke imports.
Deploy from `main` only when CI is green.
