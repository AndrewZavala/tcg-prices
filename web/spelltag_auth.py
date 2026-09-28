"""Spell Tag Google / Discord OAuth + signed session cookie."""

from __future__ import annotations

import os
import secrets
from typing import Any

import httpx
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import text
from sqlalchemy.engine import Engine

COOKIE_NAME = "spelltag_session"
COOKIE_MAX_AGE_SEC = 60 * 60 * 24 * 30  # 30 days

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "").strip()
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "").strip()
DISCORD_API = "https://discord.com/api"
SESSION_SECRET = os.environ.get("SPELLTAG_SESSION_SECRET", "").strip()
PUBLIC_URL = os.environ.get("SPELLTAG_PUBLIC_URL", "http://localhost:8001").rstrip("/")


def _parse_email_list(raw: str) -> frozenset[str]:
    return frozenset(
        part.strip().lower()
        for part in (raw or "").split(",")
        if part.strip()
    )


ADMIN_EMAILS = _parse_email_list(os.environ.get("SPELLTAG_ADMIN_EMAILS", ""))
TAGGER_EMAILS = _parse_email_list(os.environ.get("SPELLTAG_TAGGER_EMAILS", ""))

router = APIRouter(tags=["auth"])

_engine: Engine | None = None
_oauth: OAuth | None = None
_serializer: URLSafeTimedSerializer | None = None


def init_spelltag_auth(engine: Engine) -> None:
    global _engine, _oauth, _serializer
    _engine = engine
    secret = SESSION_SECRET or secrets.token_hex(32)
    if not SESSION_SECRET:
        print(
            "Spell Tag auth warning: SPELLTAG_SESSION_SECRET unset; "
            "sessions will not survive process restart"
        )
    _serializer = URLSafeTimedSerializer(secret, salt="spelltag-session")

    _oauth = OAuth()
    if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
        _oauth.register(
            name="google",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
    if DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET:
        _oauth.register(
            name="discord",
            client_id=DISCORD_CLIENT_ID,
            client_secret=DISCORD_CLIENT_SECRET,
            authorize_url="https://discord.com/oauth2/authorize",
            access_token_url=f"{DISCORD_API}/oauth2/token",
            api_base_url=f"{DISCORD_API}/",
            client_kwargs={"scope": "identify email"},
        )


def _auth_configured() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and _oauth is not None)


def _discord_configured() -> bool:
    return bool(DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET and _oauth is not None)


def _redirect_uri(provider: str = "google") -> str:
    return f"{PUBLIC_URL}/auth/{provider}/callback"


def _sign_user_id(user_id: str) -> str:
    assert _serializer is not None
    return _serializer.dumps({"uid": user_id})


def _unsign_user_id(token: str) -> str | None:
    if not _serializer:
        return None
    try:
        data = _serializer.loads(token, max_age=COOKIE_MAX_AGE_SEC)
    except (BadSignature, SignatureExpired):
        return None
    uid = data.get("uid") if isinstance(data, dict) else None
    return str(uid) if uid else None


def _cookie_secure() -> bool:
    return PUBLIC_URL.startswith("https://")


def _set_session_cookie(response: Response, user_id: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=_sign_user_id(user_id),
        max_age=COOKIE_MAX_AGE_SEC,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(),
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/")


def _fetch_user(user_id: str) -> dict[str, Any] | None:
    assert _engine is not None
    with _engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT id::text AS id, email, name, picture_url
                FROM users
                WHERE id = CAST(:id AS uuid)
                """
            ),
            {"id": user_id},
        ).mappings().first()
    return dict(row) if row else None


_PROVIDER_COLUMNS = {"google": "google_sub", "discord": "discord_id"}


def _upsert_oauth_user(
    *,
    provider: str,
    provider_id: str,
    email: str | None,
    email_verified: bool,
    name: str | None,
    picture: str | None,
) -> str:
    """Find or create the user for a provider login.

    A first login from a new provider joins an existing account only when the provider
    vouches for the email, since admin/tagger access is granted by email.
    """
    assert _engine is not None
    col = _PROVIDER_COLUMNS[provider]
    params = {"pid": provider_id, "email": email, "name": name, "picture_url": picture}
    with _engine.begin() as conn:
        row = conn.execute(
            text(f"SELECT id::text AS id FROM users WHERE {col} = :pid"), params
        ).mappings().first()
        if row is None and email and email_verified:
            row = conn.execute(
                text(
                    f"""
                    SELECT id::text AS id FROM users
                    WHERE lower(email) = lower(:email) AND {col} IS NULL
                    ORDER BY created_at
                    LIMIT 1
                    FOR UPDATE
                    """
                ),
                params,
            ).mappings().first()
        if row is not None:
            conn.execute(
                text(
                    f"""
                    UPDATE users SET
                        {col} = :pid,
                        email = COALESCE(:email, email),
                        name = COALESCE(:name, name),
                        picture_url = COALESCE(:picture_url, picture_url),
                        updated_at = NOW()
                    WHERE id = CAST(:id AS uuid)
                    """
                ),
                {**params, "id": row["id"]},
            )
            return str(row["id"])
        row = conn.execute(
            text(
                f"""
                INSERT INTO users ({col}, email, name, picture_url)
                VALUES (:pid, :email, :name, :picture_url)
                RETURNING id::text AS id
                """
            ),
            params,
        ).mappings().one()
    return str(row["id"])


def current_user(request: Request) -> dict[str, Any] | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    user_id = _unsign_user_id(token)
    if not user_id:
        return None
    return _fetch_user(user_id)


def require_user(request: Request) -> dict[str, Any]:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


def is_admin(user: dict[str, Any] | None) -> bool:
    if not user:
        return False
    email = (user.get("email") or "").strip().lower()
    return bool(email and email in ADMIN_EMAILS)


def is_tagger(user: dict[str, Any] | None) -> bool:
    if not user:
        return False
    if is_admin(user):
        return True
    email = (user.get("email") or "").strip().lower()
    return bool(email and email in TAGGER_EMAILS)


def require_admin(request: Request) -> dict[str, Any]:
    user = require_user(request)
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def require_tagger(request: Request) -> dict[str, Any]:
    user = require_user(request)
    if not is_tagger(user):
        raise HTTPException(status_code=403, detail="Tagger access required")
    return user


@router.get("/auth/google/login")
async def google_login(request: Request):
    if not _auth_configured():
        raise HTTPException(
            status_code=503,
            detail="Google sign-in is not configured (set GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)",
        )
    assert _oauth is not None
    return await _oauth.google.authorize_redirect(request, _redirect_uri())


@router.get("/auth/google/callback")
async def google_callback(request: Request):
    if not _auth_configured():
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")
    assert _oauth is not None
    try:
        token = await _oauth.google.authorize_access_token(request)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"OAuth failed: {exc}") from exc

    info = token.get("userinfo")
    if not info:
        access = token.get("access_token")
        if not access:
            raise HTTPException(status_code=400, detail="Missing Google user info")
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {access}"},
            )
            resp.raise_for_status()
            info = resp.json()

    google_sub = str(info.get("sub") or "").strip()
    if not google_sub:
        raise HTTPException(status_code=400, detail="Google account missing subject")

    user_id = _upsert_oauth_user(
        provider="google",
        provider_id=google_sub,
        email=(info.get("email") or None),
        email_verified=info.get("email_verified") is True,
        name=(info.get("name") or info.get("given_name") or None),
        picture=(info.get("picture") or None),
    )

    response = RedirectResponse(url="/", status_code=302)
    _set_session_cookie(response, user_id)
    return response


@router.get("/auth/discord/login")
async def discord_login(request: Request):
    if not _discord_configured():
        raise HTTPException(
            status_code=503,
            detail="Discord sign-in is not configured (set DISCORD_CLIENT_ID / DISCORD_CLIENT_SECRET)",
        )
    assert _oauth is not None
    return await _oauth.discord.authorize_redirect(request, _redirect_uri("discord"))


@router.get("/auth/discord/callback")
async def discord_callback(request: Request):
    if not _discord_configured():
        raise HTTPException(status_code=503, detail="Discord sign-in is not configured")
    assert _oauth is not None
    try:
        token = await _oauth.discord.authorize_access_token(request)
        resp = await _oauth.discord.get("users/@me", token=token)
        resp.raise_for_status()
        info = resp.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"OAuth failed: {exc}") from exc

    discord_id = str(info.get("id") or "").strip()
    if not discord_id:
        raise HTTPException(status_code=400, detail="Discord account missing id")

    verified = info.get("verified") is True
    avatar = info.get("avatar")
    user_id = _upsert_oauth_user(
        provider="discord",
        provider_id=discord_id,
        # Unverified Discord emails are never stored: admin/tagger roles key off email.
        email=(info.get("email") or None) if verified else None,
        email_verified=verified,
        name=(info.get("global_name") or info.get("username") or None),
        picture=(
            f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar}.png?size=64"
            if avatar
            else None
        ),
    )

    response = RedirectResponse(url="/", status_code=302)
    _set_session_cookie(response, user_id)
    return response


@router.get("/auth/me")
def auth_me(request: Request):
    user = current_user(request)
    if not user:
        return {"authenticated": False, "is_admin": False, "is_tagger": False}
    return {
        "authenticated": True,
        "id": user["id"],
        "email": user.get("email"),
        "name": user.get("name"),
        "picture_url": user.get("picture_url"),
        "is_admin": is_admin(user),
        "is_tagger": is_tagger(user),
    }


@router.post("/auth/logout")
def auth_logout():
    response = JSONResponse({"ok": True})
    _clear_session_cookie(response)
    return response


@router.get("/auth/status")
def auth_status():
    return {
        "google_configured": _auth_configured(),
        "discord_configured": _discord_configured(),
        "public_url": PUBLIC_URL,
        "redirect_uri": _redirect_uri(),
        "discord_redirect_uri": _redirect_uri("discord"),
    }
