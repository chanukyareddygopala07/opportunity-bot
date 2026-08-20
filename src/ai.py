"""Phase 14 — advisory AI layer via local Ollama.

Policies:
- AI output is ADVISORY only. It never overwrites rule-based fields
  (eligibility_status, deadline, ...) — results live in ai_assessments.
- If Ollama is unreachable or the response is unparsable, the pipeline
  simply skips the AI step (fallback = current SQLite behaviour).
- The model is told to answer "unknown" instead of guessing; a strict JSON
  shape is requested and validated before recording.

Run manually:  python -m src.ai [--limit N]
"""
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.request

from src import db

logger = logging.getLogger(__name__)

DEFAULT_URL = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434")
DEFAULT_MODEL = os.environ.get("AI_MODEL", "deepseek-r1:8b")


def _log_provider_error(provider, message, exc=None):
    logger.info("AI provider %s failed: %s", provider, message)
    try:
        db.log_error("ai", provider, message, getattr(exc, "reason", None) or None)
    except Exception:
        pass


def _retry_delay_seconds(exc, cap=45):
    """Parse Google's 'Please retry in Ns' from a 429 body; fall back to 5s."""
    try:
        body = exc.read().decode()
    except Exception:
        return 5
    match = re.search(r"retry in ([\d.]+)s", body)
    delay = float(match.group(1)) if match else 5
    return min(max(delay, 5), cap)


def configured_providers():
    """Names of AI providers with keys/endpoints configured, e.g. ["gemini"]."""
    providers = []
    if os.environ.get("OPENAI_API_KEY", "").strip():
        providers.append("openai")
    if os.environ.get("GEMINI_API_KEY", "").strip():
        providers.append("gemini")
    if is_available():
        providers.append("ollama")
    return providers

SYSTEM_PROMPT = (
    "You are a careful eligibility-checking assistant for an Indian "
    "undergraduate (B.Tech) student. Apply this startup-friendly policy:\n"
    "1. Hard exclusions (=> not_eligible) ONLY when explicitly stated: India "
    "excluded; only non-Indian citizenship/residence accepted; local work "
    "authorization required (e.g. 'must be authorized to work in the US'); "
    "degree/branch incompatible with B.Tech; year requirement incompatible "
    "(1st-year-only, 3rd-year-only, final-year-only, graduate/master's/PhD-only); "
    "deadline definitively expired.\n"
    "2. Missing formal criteria (year, branch, nationality, degree, GPA) are "
    "NOT disqualifications.\n"
    "3. Credible Indian startup, role matches CSE/software/AI/ML/data/quant "
    "skills, no explicit restriction => eligible.\n"
    "4. Credible foreign startup, role remote and no country/visa restriction "
    "=> likely_eligible. Explicitly open worldwide/international => eligible.\n"
    "5. Onsite foreign role, or unverifiable source, or unresolved "
    "location/work-authorization => unclear.\n"
    "6. Never invent deadlines or criteria; deadline_guess is null when "
    "unknown. Do not treat missing information as proof of eligibility.\n"
    "Reply with ONLY JSON in this exact shape:\n"
    "{\"india_eligibility\": {\"status\": \"eligible\"|\"likely_eligible\"|\"unclear\"|\"not_eligible\", "
    "\"confidence\": 0.0, \"reasons\": [], \"missing_information\": []}, "
    "\"degree_eligibility\": {\"status\": \"...\", \"reasons\": []}, "
    "\"branch_eligibility\": {\"status\": \"...\", \"reasons\": []}, "
    "\"year_eligibility\": {\"status\": \"...\", \"reasons\": []}, "
    "\"location_eligibility\": {\"status\": \"...\", \"remote\": false, \"location\": null, "
    "\"work_authorization_required\": null, \"reasons\": []}, "
    "\"overall_eligibility\": {\"status\": \"...\", \"reasons\": [], \"missing_information\": []}, "
    "\"verification\": {\"status\": \"verified\"|\"partially_verified\"|\"unverified\", "
    "\"official_source_found\": false, \"source_trust_score\": 0}, "
    "\"recommendation\": {\"show_to_user\": false, \"recommended\": false, "
    "\"recommendation_label\": \"eligible_india\"|\"likely_eligible_remote_startup\"|\"unclear\"|\"not_eligible\", "
    "\"reason\": \"\"}, "
    "\"deadline_guess\": \"YYYY-MM-DD\" or null}"
)

ALLOWED_VERDICTS = {"eligible", "likely_eligible", "unclear", "not_eligible"}


def is_available(url=None, timeout=3):
    url = url or DEFAULT_URL
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=timeout) as resp:
            if resp.status != 200:
                return False
            tags = json.loads(resp.read().decode())
        models = {m.get("name") for m in tags.get("models", [])}
        return DEFAULT_MODEL in models
    except Exception as exc:
        logger.info("Ollama not available: %s", exc)
        return False


def chat(prompt, system=None, url=None, model=None, timeout=180):
    url = (url or DEFAULT_URL).rstrip("/")
    model = model or DEFAULT_MODEL
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system} if system else {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 900,
            "think": False,
        },
    }).encode()
    req = urllib.request.Request(
        f"{url}/api/chat", data=payload, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode())
    return (body.get("message") or {}).get("content", "")


RUDRA_SYSTEM_PROMPT = (
    "You are Rudra, a friendly, careful AI career guide for Indian students "
    "(undergraduate B.Tech and beyond). You help with:\n"
    "- career direction and study/research planning\n"
    "- interview preparation (practice questions, STAR method, mock interviews)\n"
    "- resume guidance (structure, wording, what to include)\n"
    "- how to apply for internships, fellowships, scholarships and research "
    "programs in India and abroad\n"
    "Rules you must follow:\n"
    "1. ADVISORY ONLY: you give guidance, never guarantees. Say when you are "
    "unsure. Use 'I'm not certain — verify on the official site' when needed.\n"
    "2. Never invent facts about a program, company, deadline or eligibility. "
    "If you don't know, say so and point the student to official sources.\n"
    "3. Do not answer requests for dishonest practices (fake experience, "
    "plagiarized essays, cheating on tests) — refuse briefly and suggest an "
    "honest alternative.\n"
    "4. Do not ask for or discuss sensitive personal data like passwords, "
    "OTPs, bank details or ID numbers. Never provide financial advice as fact.\n"
    "5. Be concise (under ~250 words), structured, encouraging and practical.\n"
    "6. For a student with an 8+ CGPA interested in research, suggest real "
    "programs generically (e.g. Indian government portals, IIT/IISER summer "
    "programs, NSF REU only if they hold US citizenship/PR, DAAD, Mitacs) "
    "without inventing specific deadlines."
)

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
GEMINI_CHAT_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def gemini_stream(messages, timeout=180):
    """Stream a Gemini reply token-by-token via the SSE endpoint.

    Same message-list convention as _gemini_chat. Yields text fragments as
    they arrive (for a typing effect / instant first token). On error or
    empty output, yields nothing and the caller falls back.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return
    model = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    contents = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            continue
        contents.append({
            "role": "model" if role == "assistant" else "user",
            "parts": [{"text": str(m.get("content", ""))[:6000]}],
        })
    if not contents:
        return
    payload = {
        "contents": contents,
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 800},
    }
    if system_parts:
        payload["system_instruction"] = {"parts": [{"text": "\n".join(system_parts)}]}
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:streamGenerateContent?alt=sse&key={api_key}"
    )
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    chunk = json.loads(line[5:].strip())
                except ValueError:
                    continue
                parts = (chunk.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts)
                if text:
                    yield text
    except Exception as exc:
        logger.info("Gemini stream error: %s", exc)
        return


def _openai_chat(messages, timeout=60):
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None, None
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": 0.3,
    }).encode()
    req = urllib.request.Request(
        OPENAI_CHAT_URL, data=payload, method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
    except Exception as exc:
        _log_provider_error("openai", str(exc), exc)
        return None, None
    return (body.get("choices") or [{}])[0].get("message", {}).get("content", ""), "openai"


def _gemini_chat(messages, timeout=60):
    """Call Google Gemini (generativelanguage API). Accepts the same
    OpenAI-style message list used elsewhere; the system message becomes
    the system_instruction. Returns (reply, "gemini") or (None, None)."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None, None
    model = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    contents = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            continue
        contents.append({
            "role": "model" if role == "assistant" else "user",
            "parts": [{"text": str(m.get("content", ""))[:6000]}],
        })
    if not contents:
        return None, None
    payload = {
        "contents": contents,
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1200},
    }
    if system_parts:
        payload["system_instruction"] = {"parts": [{"text": "\n".join(system_parts)}]}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        GEMINI_CHAT_URL.format(model=model), data=data, method="POST",
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 2:
                delay = _retry_delay_seconds(exc)
                time.sleep(delay)
                continue
            _log_provider_error("gemini", f"HTTP {exc.code}", exc)
            return None, None
        except Exception as exc:
            _log_provider_error("gemini", str(exc), exc)
            return None, None
    parts = (body.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts), "gemini"


def chat_ask(user_messages, system=None, profile=None):
    """Rudra: multi-turn chat. Provider order: OpenAI (if OPENAI_API_KEY),
    then Gemini (if GEMINI_API_KEY), then local Ollama. Returns
    (reply, provider) or (None, None) when no provider is available."""
    system = system or RUDRA_SYSTEM_PROMPT
    context = ""
    if profile:
        context = (
            "STUDENT PROFILE (use for personalization, keep facts locked):\n"
            + json.dumps(profile, ensure_ascii=False)
            + "\n\n"
        )
    messages = [{"role": "system", "content": system}]
    if context:
        messages.append({"role": "system", "content": context})
    messages.extend(
        {"role": r.get("role") if r.get("role") in ("user", "assistant") else "user",
         "content": str(r.get("content", ""))[:4000]}
        for r in user_messages
    )
    reply, provider = _openai_chat(messages)
    if reply:
        return reply, provider
    reply, provider = _gemini_chat(messages)
    if reply:
        return reply, provider
    if is_available():
        url = (DEFAULT_URL or "").rstrip("/")
        payload = json.dumps({
            "model": DEFAULT_MODEL,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 600, "think": False},
        }).encode()
        req = urllib.request.Request(
            f"{url}/api/chat", data=payload, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                body = json.loads(resp.read().decode())
        except Exception as exc:
            _log_provider_error("ollama", str(exc), exc)
            return None, None
        return (body.get("message") or {}).get("content", ""), "ollama"
    return None, None


def _parse_json(text):
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def assess(opportunity, profile=None):
    """Returns a validated assessment dict or None when unavailable/bad."""
    if not is_available():
        return None
    profile = profile or _profile_dict()
    prompt = (
        "USER PROFILE:\n" + json.dumps(profile, ensure_ascii=False) +
        "\n\nOPPORTUNITY:\n" + json.dumps(opportunity, ensure_ascii=False)
    )
    raw = chat(prompt)
    data = _parse_json(raw)
    if not data:
        return None
    overall = data.get("overall_eligibility") or {}
    verdict = str(
        overall.get("status") or data.get("verdict") or "unclear"
    ).strip().lower()
    if verdict not in ALLOWED_VERDICTS:
        verdict = "unclear"
    reasons = overall.get("reasons") or [data.get("reason")]
    reason = "; ".join(str(r) for r in reasons if r)
    missing = overall.get("missing_information") or []
    deadline_guess = data.get("deadline_guess")
    if deadline_guess:
        try:
            deadline_guess = str(deadline_guess)[:10]
        except Exception:
            deadline_guess = None
    try:
        confidence = max(
            0.0, min(1.0, float(overall.get("confidence") if overall.get("confidence") is not None
                                else data.get("confidence", 0.0)))
        )
    except (TypeError, ValueError):
        confidence = 0.0
    result = {
        "verdict": verdict,
        "reason": reason[:500],
        "deadline_guess": deadline_guess,
        "confidence": confidence,
    }
    if missing:
        result["missing_information"] = missing
    return result


def _profile_dict():
    from src import store
    profile = store.load_profile() or {}
    return {k: v for k, v in profile.items() if k not in ("chat_id",)}


def assess_new(limit=5, profile=None):
    """Assess opportunities that have no ai_assessments row yet."""
    if not is_available():
        return 0
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT id, title, organization, description, eligibility_status, "
            "deadline, funding, location FROM opportunities "
            "WHERE duplicate_of IS NULL AND id NOT IN "
            "(SELECT opportunity_id FROM ai_assessments) "
            "AND eligibility_status != 'not_eligible' "
            "ORDER BY id LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    done = 0
    for row in rows:
        opp = dict(row)
        assessment = assess(opp, profile=profile)
        if assessment is None:
            continue
        db.record_ai_assessment(
            opportunity_id=opp["id"],
            verdict=assessment["verdict"],
            reason=assessment["reason"],
            deadline_guess=assessment["deadline_guess"],
            confidence=assessment["confidence"],
            model=DEFAULT_MODEL,
        )
        done += 1
    return done


def run(limit=5):
    db.init_db()
    done = assess_new(limit=limit)
    print(f"ai_assessed={done}")
    return done


if __name__ == "__main__":
    limit = 5
    if "--limit" in sys.argv:
        try:
            limit = int(sys.argv[sys.argv.index("--limit") + 1])
        except (ValueError, IndexError):
            pass
    run(limit=limit)
    sys.exit(0)