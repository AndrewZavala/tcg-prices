"""Spell Tag — public Pokémon TCG catalog (standalone from Manifest Bread).

Serves Spell Tag UI + read-only Pokémon catalog APIs.
Does not mount inventory, opportunities, collection, or other Manifest Bread routes.
"""

from __future__ import annotations

import os
import secrets

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, text
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import Response

from pokemon_api import init_pokemon_api, router as pokemon_router
from spelltag_auth import init_spelltag_auth, router as auth_router

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://tcg:tcg_secret@localhost:5432/tcg_buylist",
)
CORS_ORIGINS = os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:8001,http://127.0.0.1:8001",
).split(",")
SESSION_SECRET = os.environ.get("SPELLTAG_SESSION_SECRET", "").strip() or secrets.token_hex(32)

app = FastAPI(
    title="Spell Tag",
    version="0.1.0",
    description="Unofficial Pokémon TCG search at spelltag.com. Not affiliated with Manifest Bread.",
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "migrations")

POKEMON_MIGRATIONS = (
    "025_pokemon_catalog.sql",
    "026_pokemon_oracle.sql",
    "027_pokemon_subtypes.sql",
    "028_pokemon_species.sql",
    "029_pokemon_tcgplayer.sql",
    "030_pokemon_species_groups.sql",
    "031_spelltag_users.sql",
)


class DevNoCacheMiddleware(BaseHTTPMiddleware):
    """Avoid stale HTML/JS/CSS while iterating locally."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/static/") or path in (
            "/",
            "/pokemon",
            "/spell-tag",
        ):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


# SessionMiddleware is required for Authlib OAuth state (innermost of these runs first on request)
app.add_middleware(DevNoCacheMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in CORS_ORIGINS if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="lax",
    https_only=os.environ.get("SPELLTAG_PUBLIC_URL", "").startswith("https://"),
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
init_pokemon_api(engine)
init_spelltag_auth(engine)
app.include_router(pokemon_router)
app.include_router(auth_router)


def _apply_sql_file(conn, filename: str) -> None:
    path = os.path.join(MIGRATIONS_DIR, filename)
    if os.path.isfile(path):
        conn.execute(text(open(path, encoding="utf-8").read()))


@app.on_event("startup")
def startup_migrations() -> None:
    try:
        with engine.begin() as conn:
            for name in POKEMON_MIGRATIONS:
                _apply_sql_file(conn, name)
    except Exception as exc:
        print(f"Spell Tag migration warning: {exc}")


def _page(name: str) -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, name))


@app.get("/")
def home():
    return _page("spell-tag.html")


@app.get("/pokemon")
def pokemon_page():
    return _page("spell-tag.html")


@app.get("/spell-tag")
def spell_tag_page():
    return _page("spell-tag.html")


@app.get("/health")
def health():
    return {"ok": True, "service": "spell-tag"}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
