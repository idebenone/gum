"""Simple FastAPI server to accept text observations per user and expose recent propositions.

Endpoints:
- POST /users/{user}/observe  { "text": "..." }  -> queues text for that user (requires auth)
- GET  /users/{user}/recent   -> returns recent propositions (requires auth)
- POST /users/login           -> authenticate and get JWT token
- POST /users/register        -> register new user

Per-user observations are stored in Redis for processing by background workers.
Recent propositions are retrieved from the database.

Run with:
    uvicorn api.server:app --host 0.0.0.0 --port 8000
"""
from typing import Dict, Any
import asyncio
import logging
import os
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from dotenv import load_dotenv

from .config.database import init_db
from .middleware import validate_token
from .models import User, Proposition
from .schemas.gum_schemas import ObservePayload
from .schemas.auth_schemas import LoginPayload, RegisterPayload
from .services.auth_services import login_user_service, register_user_service
from .services.redis_service import RedisObservationService
from .worker import _background_batch_processor

load_dotenv()

logger = logging.getLogger("gum.api")
logger.setLevel(logging.INFO)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

redis_service = RedisObservationService(
    redis_url=os.getenv("REDIS_URL", "redis://localhost:6379")
)

async def _user_exists_in_db(username: str) -> bool:
    """Check if a user exists in the database."""
    try:
        engine, Session = await init_db()
        async with Session() as session:
            async with session.begin():
                res = await session.execute(select(User).where(User.username == username))
                user = res.scalars().first()
                return user is not None
    except Exception as e:
        logger.error(f"Error checking user existence: {e}")
        return False

async def _get_recent_propositions(user_id: int, limit: int = 10) -> list[Dict[str, Any]]:
    """Fetch recent propositions for a user directly from database."""
    try:
        engine, Session = await init_db()
        async with Session() as session:
            async with session.begin():
                # Query recent propositions for the user
                res = await session.execute(
                    select(Proposition)
                    .where(Proposition.user_id == user_id)
                    .order_by(Proposition.created_at.desc())
                    .limit(limit)
                )
                propositions = res.scalars().all()
                
                out = []
                for p in propositions:
                    out.append({
                        "id": p.id,
                        "text": p.text,
                        "reasoning": p.reasoning,
                        "confidence": p.confidence,
                        "created_at": p.created_at.isoformat() if p.created_at else None,
                        "observations": [
                            {"id": o.id, "content": o.content}
                            for o in getattr(p, "observations", [])
                        ]
                    })
                return out
    except Exception as e:
        logger.error(f"Error fetching recent propositions for user {user_id}: {e}")
        return []


@app.post("/api/login")
async def login_user(payload: LoginPayload):
    if not payload.username or not payload.password:
        raise HTTPException(status_code=400, detail="username and password required")

    return await login_user_service(payload)

@app.post("/api/register")
async def register_user(payload: RegisterPayload):
    if not payload.username or not payload.username.strip():
        raise HTTPException(status_code=400, detail="username is required")

    return await register_user_service(payload)

@app.post("/api/users/{user}/observe")
async def observe_text(user: str, payload: ObservePayload, token: dict = Depends(validate_token)):
    """Queue text observation for a user via Redis.
    
    Requires valid JWT token with matching username in token['sub'].
    Observations are stored in Redis for processing by background workers.
    
    Args:
        user: username (must match token claims)
        payload: { "text": "...", "model": "..." }
        token: validated JWT token claims
    
    Returns:
        { "status": "ok", "queued": <queue_size> }
    """
    token_user = token.get("sub")
    if token_user != user:
        raise HTTPException(status_code=403, detail="Token does not match requested user")
    
    if not await _user_exists_in_db(user):
        raise HTTPException(status_code=404, detail="User not found")
    
    if not payload.text or not payload.text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    
    user_id = token.get("user_id")
    if not user_id:
        raise HTTPException(status_code=500, detail="user_id not found in token")

    observation_id = str(uuid4())
    try:
        loop = asyncio.get_event_loop()
        queue_size = await loop.run_in_executor(
            None,
            lambda: redis_service.add_observation(
                username=user,
                user_id=user_id,
                observer_name="api_text",
                content=payload.text.strip(),
                content_type="text",
                observation_id=observation_id,
            )
        )
        print(f"Queued observation {observation_id} for user {user}:{user_id}")
        return {"status": "ok", "queued": queue_size}
    except Exception as e:
        print(f"Error queuing observation for user {user}: {e}")
        raise HTTPException(status_code=500, detail="Failed to queue observation")

@app.get("/api/users/{user}/recent")
async def recent(user: str, limit: int = 10, token: dict = Depends(validate_token)):
    """Fetch recent propositions for a user.
    
    Requires valid JWT token with matching username in token['sub'].
    
    Args:
        user: username (must match token claims)
        limit: max propositions to return
        token: validated JWT token claims
    
    Returns:
        List of proposition objects with observations
    """
    token_user = token.get("sub")
    if token_user != user:
        raise HTTPException(status_code=403, detail="Token does not match requested user")
    user_id = token.get("user_id")
    if not user_id:
        raise HTTPException(status_code=500, detail="user_id not found in token")
    props = await _get_recent_propositions(user_id, limit=limit)
    return props

@app.on_event("startup")
async def _startup():
    global _background_task
    print("[STARTUP] FastAPI startup event triggered!")
    _background_task = asyncio.create_task(_background_batch_processor(redis_service))

@app.on_event("shutdown")
async def _shutdown():
    """Shutdown the background batch processor."""
    global _background_task
    print("API shutdown: stopping background batch processor")
    if _background_task:
        _background_task.cancel()
        try:
            await _background_task
        except asyncio.CancelledError:
            pass