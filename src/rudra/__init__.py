"""Rudra — the AI career assistant layer.

Architecture:

    Widget (static JS, decoupled)
      → Rudra API (Flask JSON/SSE endpoints, authenticated)
        → Orchestrator (intent routing, grounded prompt building)
          → Tool/Context Router (deterministic, allow-listed)
            → AAWARA services (db/scoring/trust — never raw SQL from prompts)

Invariants:
- Tools are the ONLY way a chat turn touches data. There is no free-form
  query path; every tool is scoped to the calling user's own rows.
- Only minimum-necessary context leaves the server, projected through
  explicit field whitelists. Never secrets, never other users' data.
- Crawled opportunity text is untrusted: it is delimited and labelled in
  prompts so model output distinguishes DATABASE FACT from RECOMMENDATION.
"""
