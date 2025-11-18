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

import jwt
from fastapi import FastAPI, HTTPException, Depends, Header
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from gum import gum as GumClass
from gum.observers import Text
from gum.models import User
from .schemas.gum_schemas import ObservePayload
from .schemas.auth_schemas import LoginPayload, RegisterPayload

from .services.auth_services import login_user_service, register_user_service
from .services.redis_service import RedisObservationService
from .services.proposition_service import process_observation_batch
from gum.db_utils import get_user_session
from openai import AsyncOpenAI

logger = logging.getLogger("gum.api")
app = FastAPI()

# Initialize Redis observation service
redis_service = RedisObservationService(
    redis_url=os.getenv("REDIS_URL", "redis://localhost:6379")
)

# ============================================================================
# Background Worker Configuration
# ============================================================================

# Configuration for background batch processing
BACKGROUND_WORKER_CONFIG = {
    "flush_interval_seconds": int(os.getenv("FLUSH_INTERVAL_SECONDS", "30")),
    "min_batch_size": int(os.getenv("MIN_BATCH_SIZE", "1")),
    "max_concurrent_processing": int(os.getenv("MAX_CONCURRENT_PROCESSING", "10")),
}

# Global state for background worker
_background_task: asyncio.Task | None = None
_user_processing_locks: Dict[str, asyncio.Lock] = {}  # Per-user locks for serialized processing
_lock_creation_lock = asyncio.Lock()


async def _get_user_lock(username: str) -> asyncio.Lock:
    """Get or create a per-user lock for serialized observation processing."""
    async with _lock_creation_lock:
        if username not in _user_processing_locks:
            _user_processing_locks[username] = asyncio.Lock()
        return _user_processing_locks[username]


async def _background_batch_processor():
    """Background task to periodically process observations from Redis using stateless service.
    
    This task:
    1. Scans Redis for users with pending observations
    2. Processes observations with bounded concurrency (semaphore)
    3. Calls proposition_service.process_observation_batch() for each user
    4. Handles errors gracefully (logs + continues)
    5. No gum instance caching needed (stateless processing)
    """
    semaphore = asyncio.Semaphore(BACKGROUND_WORKER_CONFIG["max_concurrent_processing"])
    
    logger.info(f"Background batch processor starting with config: {BACKGROUND_WORKER_CONFIG}")
    
    # Initialize LLM client for proposition generation
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        logger.error("OPENAI_API_KEY not set; background processor will fail")
    llm_client = AsyncOpenAI(api_key=openai_api_key) if openai_api_key else None
    llm_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    
    while True:
        try:
            # Sleep first to give observations time to accumulate
            await asyncio.sleep(BACKGROUND_WORKER_CONFIG["flush_interval_seconds"])
            
            # Get all pending users from Redis
            loop = asyncio.get_event_loop()
            pending_users = await loop.run_in_executor(
                None,
                redis_service.get_all_pending_users,
            )
            
            if not pending_users:
                logger.debug("No pending observations in Redis")
                continue
            
            logger.info(f"Found {len(pending_users)} users with pending observations")
            
            # Process each user's observations with bounded concurrency
            tasks = [
                _process_user_observations_stateless(
                    username, user_id, semaphore, llm_client, llm_model
                )
                for username, user_id in pending_users
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Error processing user batch: {result}")
            
        except asyncio.CancelledError:
            logger.info("Background batch processor shutting down")
            break
        except Exception as e:
            logger.error(f"Error in background batch processor: {e}", exc_info=True)


async def _process_user_observations_stateless(
    username: str,
    user_id: int,
    semaphore: asyncio.Semaphore,
    llm_client: AsyncOpenAI,
    llm_model: str,
):
    """Process observations for a single user using stateless proposition service.
    
    Args:
        username: username
        user_id: user_id from database
        semaphore: concurrency limiter
        llm_client: AsyncOpenAI client
        llm_model: LLM model name
    """
    async with semaphore:
        # Get per-user lock to serialize observation processing
        user_lock = await _get_user_lock(username)
        
        async with user_lock:
            try:
                # Get min batch size from config
                min_batch_size = BACKGROUND_WORKER_CONFIG["min_batch_size"]
                
                # Get queue size for this user
                loop = asyncio.get_event_loop()
                queue_size = await loop.run_in_executor(
                    None,
                    lambda: redis_service.get_queue_size(username, user_id),
                )
                
                if queue_size < min_batch_size:
                    logger.debug(f"User {username}:{user_id} has {queue_size} observations (< min {min_batch_size})")
                    return
                
                logger.info(f"Processing {queue_size} observations for user {username}:{user_id}")
                
                # Pop observations from Redis
                observations = await loop.run_in_executor(
                    None,
                    lambda: redis_service.pop_observations(username, user_id, count=None),
                )
                
                if not observations:
                    return
                
                # Get database session
                from gum.db_utils import get_user_session
                session = await get_user_session()
                
                # Import prompts from gum config (or use defaults)
                from gum.prompts.gum import PROPOSE_PROMPT, SIMILAR_PROMPT, REVISE_PROMPT
                
                try:
                    # Call stateless proposition service
                    result = await process_observation_batch(
                        observations=observations,
                        user_id=user_id,
                        user_name=username,
                        model=llm_model,
                        llm_client=llm_client,
                        session=session,
                        propose_prompt=PROPOSE_PROMPT,
                        similar_prompt=SIMILAR_PROMPT,
                        revise_prompt=REVISE_PROMPT,
                    )
                    logger.info(f"Processed observations for {username}:{user_id}: {result}")
                    
                except Exception as e:
                    logger.error(f"Error calling proposition service for {username}:{user_id}: {e}", exc_info=True)
                    # Re-queue observations back to Redis on failure
                    try:
                        await loop.run_in_executor(
                            None,
                            lambda: [
                                redis_service.add_observation(
                                    username,
                                    user_id,
                                    obs.get("observer_name", "unknown"),
                                    obs.get("content", ""),
                                    obs.get("content_type", "text"),
                                    observation_id=obs.get("id"),
                                )
                                for obs in observations
                            ],
                        )
                        logger.info(f"Re-queued {len(observations)} observations for {username}:{user_id}")
                    except Exception as requeue_error:
                        logger.error(f"Failed to re-queue observations: {requeue_error}")
                    raise
                finally:
                    await session.close()
                
            except Exception as e:
                logger.error(f"Error processing observations for {username}:{user_id}: {e}", exc_info=True)

# ============================================================================
# Token Validation & Authentication
# ============================================================================

def _get_jwt_secret() -> str:
    """Get JWT secret from environment or use default (NOT SECURE for production)."""
    return os.getenv("JWT_SECRET", "change-me")

async def validate_token(authorization: str | None = Header(None)) -> dict[str, Any]:
    """Dependency to validate JWT token from Authorization header.
    
    Expected header format: Authorization: Bearer <token>
    
    Returns:
        dict with token claims (sub=username, user_id, exp)
    
    Raises:
        HTTPException 401 if token is missing, invalid, or expired
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise ValueError("Invalid scheme")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Authorization header format. Expected: Bearer <token>")
    
    try:
        secret = _get_jwt_secret()
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")

# ============================================================================
# Gum Instance Management
# ============================================================================
_gums: Dict[str, GumClass] = {}
_lock = asyncio.Lock()

async def _create_gum_for_user(user_name: str, model: str | None = None, api_base: str | None = None, min_batch_size: int = 5, max_batch_size: int = 50) -> GumClass:
    obs = Text()
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

async def _user_exists_in_db(username: str) -> bool:
    """Check if a user exists in the database."""
    from sqlalchemy import select
    try:
        g = await get_or_create_gum(username)
        async with g._session() as session:
            res = await session.execute(select(User).where(User.username == username))
            user = res.scalars().first()
            return user is not None
    except Exception as e:
        logger.error(f"Error checking user existence: {e}")
        return False

@app.post("/users/{user}/observe")
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
    # Verify token belongs to the user making the request
    token_user = token.get("sub")
    if token_user != user:
        raise HTTPException(status_code=403, detail="Token does not match requested user")
    
    # Verify the user exists in the database (to get user_id)
    if not await _user_exists_in_db(user):
        raise HTTPException(status_code=404, detail="User not found")
    
    if not payload.text or not payload.text.strip():
        raise HTTPException(status_code=400, detail="text is required")

    # Get user_id from token claims
    user_id = token.get("user_id")
    if not user_id:
        raise HTTPException(status_code=500, detail="user_id not found in token")

    # Store observation in Redis for background processing
    observation_id = str(uuid4())
    try:
        # Use loop's thread executor to run blocking Redis call
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
        logger.info(f"Queued observation {observation_id} for user {user}:{user_id}")
        return {"status": "ok", "queued": queue_size}
    except Exception as e:
        logger.error(f"Error queuing observation for user {user}: {e}")
        raise HTTPException(status_code=500, detail="Failed to queue observation")

@app.get("/users/{user}/recent")
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
    # Verify token belongs to the user making the request
    token_user = token.get("sub")
    if token_user != user:
        raise HTTPException(status_code=403, detail="Token does not match requested user")
    
    # Verify the user exists in the database
    if not await _user_exists_in_db(user):
        raise HTTPException(status_code=404, detail="User not found")
    
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

@app.on_event("startup")
async def _startup():
    """Start the background batch processor on server startup."""
    global _background_task
    logger.info("API startup: starting background batch processor")
    _background_task = asyncio.create_task(_background_batch_processor())


@app.on_event("shutdown")
async def _shutdown():
    """Shutdown the background batch processor and clean up resources."""
    global _background_task
    logger.info("API shutdown: stopping background batch processor and cleaning up gum instances")
    
    # Cancel background task
    if _background_task:
        _background_task.cancel()
        try:
            await _background_task
        except asyncio.CancelledError:
            pass
    
    # Clean up gum instances from background worker (handled by background task on cancel)
    # Also clean up any instances in _gums dict
    async with _lock:
        for user, g in list(_gums.items()):
            try:
                await g.__aexit__(None, None, None)
            except Exception:
                logger.exception("Error shutting down gum for user %s", user)
        _gums.clear()

@app.post("/users/login")
async def login_user(payload: LoginPayload):
    if not payload.username or not payload.password:
        raise HTTPException(status_code=400, detail="username and password required")

    g: GumClass = await get_or_create_gum(payload.username)
    return await login_user_service(payload, g)

@app.post("/users/register")
async def register_user(payload: RegisterPayload):
    if not payload.username or not payload.username.strip():
        raise HTTPException(status_code=400, detail="username is required")

    g = await get_or_create_gum(payload.username)
    return await register_user_service(payload, g)