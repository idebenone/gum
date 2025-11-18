"""Simple FastAPI server to accept text observations per user and expose recent propositions.

Endpoints:
- POST /users/{user}/observe  { "text": "..." }  -> queues text for that user
- GET  /users/{user}/recent   -> returns recent propositions

Per-user data separation: each user gets a `gum` instance created on demand.

Run with:
    uvicorn api.server:app --host 0.0.0.0 --port 8000

Note: this creates gum instances that persist in memory; in production you may
want a shared pool or external orchestration.
"""
from typing import Dict, Any
import asyncio
import logging
import os
from datetime import datetime, timedelta

import jwt
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from gum_old import gum as GumClass
from gum_old.observers import TextObserver

logger = logging.getLogger("gum.api")
app = FastAPI()

_gums: Dict[str, GumClass] = {}
_lock = asyncio.Lock()

class ObservePayload(BaseModel):
    text: str
    model: str | None = None

class RegisterPayload(BaseModel):
    username: str
    first_name: str | None = None
    last_name: str | None = None
    location: str | None = None
    gender: str | None = None
    dob: str | None = None
    email: str | None = None
    password: str | None = None

class LoginPayload(BaseModel):
    username: str
    password: str

async def _create_gum_for_user(user_name: str, model: str | None = None, api_base: str | None = None, min_batch_size: int = 5, max_batch_size: int = 50) -> GumClass:
    obs = TextObserver()
    g = GumClass(user_name, model or "gpt-4o-mini", obs, min_batch_size=min_batch_size, max_batch_size=max_batch_size, api_base=api_base)
    await g.__aenter__()
    return g

async def get_or_create_gum(user_name: str, model: str | None = None, api_base: str | None = None) -> GumClass:
    async with _lock:
        if user_name in _gums:
            return _gums[user_name]
        g = await _create_gum_for_user(user_name, model=model, api_base=api_base)
        _gums[user_name] = g
        logger.info(f"Created gum instance for user '{user_name}'")
        return g

@app.post("/users/{user}/observe")
async def observe_text(user: str, payload: ObservePayload):
    if not payload.text or not payload.text.strip():
        raise HTTPException(status_code=400, detail="text is required")

    g = await get_or_create_gum(user, model=payload.model)

    text_obs = None
    for o in g.observers:
        if getattr(o, "name", "") == "TextObserver":
            text_obs = o
            break

    if text_obs is None:
        raise HTTPException(status_code=500, detail="TextObserver not configured for this gum instance")

    await text_obs.add_text(payload.text)
    queued = g.batcher.size()
    return {"status": "ok", "queued": queued}


@app.post("/users/register")
async def register_user(payload: RegisterPayload):
    """Register or update a user in the database.

    This will create a gum instance for the user (if needed) and persist
    the provided profile fields. Password is stored verbatim here; in
    production you should hash it.
    """
    if not payload.username or not payload.username.strip():
        raise HTTPException(status_code=400, detail="username is required")

    g = await get_or_create_gum(payload.username)

    async with g._session() as session:
        from gum_old.models import User

        res = await session.execute(
            __import__("sqlalchemy").select(User).where(User.username == payload.username)
        )
        user = res.scalars().first()
        if user is None:
            user = User(username=payload.username)
            session.add(user)
            await session.flush()

        # set provided fields
        if payload.first_name is not None:
            user.first_name = payload.first_name
        if payload.last_name is not None:
            user.last_name = payload.last_name
        if payload.location is not None:
            user.location = payload.location
        if payload.gender is not None:
            user.gender = payload.gender
        if payload.dob is not None:
            user.dob = payload.dob
        if payload.email is not None:
            user.email = payload.email
        if payload.password is not None:
            user.password = payload.password

        await session.commit()

    return {
        "status": "ok",
        "user": {
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "location": user.location,
            "gender": user.gender,
            "dob": str(user.dob) if getattr(user, "dob", None) is not None else None,
            "email": user.email,
        },
    }

@app.get("/users/{user}/recent")
async def recent(user: str, limit: int = 10):
    g = await get_or_create_gum(user)
    props = await g.recent(limit=limit, include_observations=True)
    out = []
    for p in props:
        out.append({
            "id": p.id,
            "text": p.text,
            "reasoning": p.reasoning,
            "confidence": p.confidence,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "observations": [ {"id": o.id, "content": o.content} for o in getattr(p, "observations", []) ]
        })
    return out

@app.on_event("shutdown")
async def _shutdown():
    logger.info("API shutdown: cleaning up gum instances")
    async with _lock:
        for user, g in list(_gums.items()):
            try:
                await g.__aexit__(None, None, None)
            except Exception:
                logger.exception("Error shutting down gum for user %s", user)
        _gums.clear()


@app.post("/users/login")
async def login_user(payload: LoginPayload):
    """Authenticate user and return a JWT access token.

    Note: passwords are stored in plaintext in this implementation. For
    production use a secure password hash (bcrypt) and secure secret.
    """
    if not payload.username or not payload.password:
        raise HTTPException(status_code=400, detail="username and password required")

    g = await get_or_create_gum(payload.username)

    async with g._session() as session:
        from gum_old.models import User
        from sqlalchemy import select

        res = await session.execute(select(User).where(User.username == payload.username))
        user = res.scalars().first()
        if user is None or user.password != payload.password:
            raise HTTPException(status_code=401, detail="invalid credentials")

    secret = os.getenv("JWT_SECRET", "change-me")
    now = datetime.utcnow()
    exp = now + timedelta(hours=24)
    token = jwt.encode({"sub": user.username, "user_id": user.id, "exp": exp}, secret, algorithm="HS256")

    return {"access_token": token, "token_type": "bearer", "expires_at": exp.isoformat()}
