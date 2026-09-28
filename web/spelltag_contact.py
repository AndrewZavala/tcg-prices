"""Spell Tag contact form — messages are stored in Postgres (no outbound email)."""

from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Engine

from spelltag_auth import current_user

router = APIRouter(tags=["contact"])

_engine: Engine | None = None

MAX_PER_IP_PER_HOUR = 5
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def init_spelltag_contact(engine: Engine) -> None:
    global _engine
    _engine = engine


class ContactBody(BaseModel):
    topic: Literal["bug", "tagger", "other"]
    email: str | None = Field(default=None, max_length=254)
    message: str = Field(min_length=1, max_length=4000)
    # Honeypot: hidden from people, filled in by bots.
    website: str | None = Field(default=None, max_length=200)


def _client_ip(request: Request) -> str:
    # Caddy replaces X-Forwarded-For with the real client address.
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


@router.post("/api/contact")
def submit_contact(body: ContactBody, request: Request) -> dict[str, bool]:
    if body.website:
        return {"ok": True}

    message = body.message.strip()
    if len(message) < 5:
        raise HTTPException(status_code=400, detail="Please write a little more in your message.")

    user = current_user(request)
    email = (body.email or "").strip() or (user.get("email") if user else None)
    if email and not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="That email address doesn't look right.")
    if body.topic == "tagger" and not email:
        raise HTTPException(
            status_code=400,
            detail="Tagger requests need an email (or sign in) so we can set up your account.",
        )

    ip = _client_ip(request)
    assert _engine is not None
    with _engine.begin() as conn:
        recent = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM spelltag_contact_messages
                WHERE ip = :ip AND created_at > NOW() - INTERVAL '1 hour'
                """
            ),
            {"ip": ip},
        ).scalar_one()
        if recent >= MAX_PER_IP_PER_HOUR:
            raise HTTPException(
                status_code=429,
                detail="You've sent several messages recently. Please try again in an hour.",
            )
        conn.execute(
            text(
                """
                INSERT INTO spelltag_contact_messages
                    (topic, email, message, user_id, ip, user_agent)
                VALUES (:topic, :email, :message, :user_id, :ip, :user_agent)
                """
            ),
            {
                "topic": body.topic,
                "email": email,
                "message": message,
                "user_id": user["id"] if user else None,
                "ip": ip,
                "user_agent": (request.headers.get("user-agent") or "")[:400],
            },
        )
    return {"ok": True}
