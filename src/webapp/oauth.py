"""Google + GitHub OAuth2 (authorization-code flow) using only the stdlib.

Redirect the user to the provider, exchange the authorization code server-side,
then find-or-create a local account linked by the provider's stable user id.
"""
import json
import os
import re
import secrets
import urllib.parse
import urllib.request

from src import db

STATE_COOKIE = "opp_oauth_state"

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_EMAILS_URL = "https://api.github.com/user/emails"


class OAuthError(Exception):
    pass


def _env(keys):
    for key in keys:
        value = os.environ.get(key)
        if value:
            return value
    raise OAuthError(f"missing env var {keys[0]}")


def redirect_base():
    return os.environ.get("OAUTH_REDIRECT_BASE", "http://localhost:8080").rstrip("/")


def redirect_uri(provider):
    return f"{redirect_base()}/auth/{provider}/callback"


def new_state():
    return secrets.token_urlsafe(24)


def _urlopen_json(url, data=None, headers=None, method=None):
    payload = (
        urllib.parse.urlencode(data).encode() if data is not None else None
    )
    req = urllib.request.Request(
        url, data=payload, headers=headers or {}, method=method
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def google_auth_url(state):
    params = {
        "client_id": _env(["GOOGLE_CLIENT_ID"]),
        "redirect_uri": redirect_uri("google"),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    return GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params)


def google_exchange(code):
    token = _urlopen_json(
        GOOGLE_TOKEN_URL,
        data={
            "client_id": _env(["GOOGLE_CLIENT_ID"]),
            "client_secret": _env(["GOOGLE_CLIENT_SECRET"]),
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri("google"),
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    access_token = token.get("access_token")
    if not access_token:
        raise OAuthError("google token exchange failed")
    info = _urlopen_json(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    provider_id = info.get("id")
    if not provider_id:
        raise OAuthError("google userinfo missing id")
    return {
        "provider": "google",
        "provider_id": str(provider_id),
        "email": info.get("email"),
        # Google explicitly tells us whether the email is verified; account
        # linking by email is only safe when this is true.
        "email_verified": bool(info.get("email_verified")),
        "name": info.get("name"),
    }


def github_auth_url(state):
    params = {
        "client_id": _env(["GITHUB_CLIENT_ID"]),
        "redirect_uri": redirect_uri("github"),
        "scope": "read:user user:email",
        "state": state,
    }
    return GITHUB_AUTH_URL + "?" + urllib.parse.urlencode(params)


def github_exchange(code):
    token = _urlopen_json(
        GITHUB_TOKEN_URL,
        data={
            "client_id": _env(["GITHUB_CLIENT_ID"]),
            "client_secret": _env(["GITHUB_CLIENT_SECRET"]),
            "code": code,
            "redirect_uri": redirect_uri("github"),
        },
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    access_token = token.get("access_token")
    if not access_token:
        raise OAuthError("github token exchange failed")
    info = _urlopen_json(
        GITHUB_USER_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "opportunity-radar",
        },
    )
    provider_id = info.get("id")
    if not provider_id:
        raise OAuthError("github userinfo missing id")
    email = info.get("email")
    email_verified = False
    # /user email can be null or unverified; the emails endpoint is the
    # source of truth for a primary verified address.
    try:
        emails = _urlopen_json(
            GITHUB_EMAILS_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "opportunity-radar",
            },
        )
        if isinstance(emails, list):
            primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
            if primary and primary.get("email"):
                email, email_verified = primary["email"], True
            elif not email:
                first_verified = next((e for e in emails if e.get("verified") and e.get("email")), None)
                if first_verified:
                    email, email_verified = first_verified["email"], True
    except Exception:
        pass  # fall through with the possibly-null profile email
    return {
        "provider": "github",
        "provider_id": str(provider_id),
        "email": email,
        "email_verified": email_verified,
        "name": info.get("name") or info.get("login"),
    }


def unique_username(name, email):
    """Slug-ify a name/email local-part and make it unique across users."""
    first = (name or "").strip().split()
    base = re.sub(r"[^a-z0-9_.-]", "", (first[0] if first else (email or "user")).lower())
    base = re.sub(r"_+", "_", base).strip("._-")[:20] or "user"
    candidate = base
    counter = 2
    while db.get_user_by_username(candidate):
        candidate = f"{base}{counter}"
        counter += 1
    return candidate


def find_or_create_user(profile):
    """Return a user id linked to the OAuth profile, creating/linking as needed.

    Email-based account linking happens ONLY when the provider asserts the
    email is verified — otherwise an attacker who sets an arbitrary
    unverified email at the provider could take over a local account.
    """
    provider = profile["provider"]
    provider_id = profile["provider_id"]
    user = db.get_user_by_oauth(provider, provider_id)
    if user:
        return user["id"]
    email = profile.get("email")
    existing = (
        db.get_user_by_email(email)
        if email and profile.get("email_verified")
        else None
    )
    if existing:
        db.link_oauth(existing["id"], provider, provider_id)
        return existing["id"]
    from src import store

    seed = store.load_profile() or {}
    username = unique_username(profile.get("name"), email or "")
    # Avoid colliding with an existing (unverified-email) local account.
    while db.get_user_by_username(username):
        username = f"{username}x"
    user_id = db.create_user(
        username,
        password_hash=None,
        profile=seed,
        email=email if profile.get("email_verified") else None,
        google_id=str(provider_id) if provider == "google" else None,
        github_id=str(provider_id) if provider == "github" else None,
    )
    return user_id