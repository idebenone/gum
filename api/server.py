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
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .models import User, Proposition
from .config.database import init_db
from .schemas.gum_schemas import ObservePayload
from .schemas.auth_schemas import LoginPayload, RegisterPayload

from .services.auth_services import login_user_service, register_user_service
from .services.redis_service import RedisObservationService
from .services.proposition_service import process_observation_batch
from openai import AsyncOpenAI
from dotenv import load_dotenv
from .prompts.gum_prompts import PROPOSE_PROMPT, SIMILAR_PROMPT, REVISE_PROMPT
load_dotenv()

logger = logging.getLogger("gum.api")
logger.setLevel(logging.INFO)

app = FastAPI()

# Enable CORS for all origins (customize as needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change to specific origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    print("[BATCHER] Background batch processor STARTED!")
    logger.info("[BATCHER] Background batch processor STARTED!")
    
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
    
    # Get LLM configuration (OpenAI or Ollama)
    llm_model, api_base, api_key = _get_llm_config()
    
    if not api_key:
        logger.error("No LLM API key configured. Please set either OPENAI_API_KEY or GUM_LM_API_KEY.")
        return
    
    # Initialize appropriate LLM client
    if api_base:
        # Use Ollama
        logger.info(f"Using Ollama LLM: {llm_model} at {api_base}")
        llm_client = AsyncOpenAI(api_key=api_key, base_url=api_base)
    else:
        # Use OpenAI
        logger.info(f"Using OpenAI LLM: {llm_model}")
        llm_client = AsyncOpenAI(api_key=api_key)
    
    while True:
        try:
            # Get all pending users from Redis
            loop = asyncio.get_event_loop()
            pending_users = await loop.run_in_executor(
                None,
                redis_service.get_all_pending_users,
            )
            
            if not pending_users:
                logger.debug("No pending observations in Redis")
            else:
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
            
            # Sleep after processing (or if no pending users)
            await asyncio.sleep(BACKGROUND_WORKER_CONFIG["flush_interval_seconds"])
            
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
                
                # Initialize DB and get Session factory
                engine, Session = await init_db()
                
                try:
                    # Create a session context
                    async with Session() as session:
                        async with session.begin():
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
# Configuration & Constants
# ============================================================================

def _get_llm_config() -> tuple[str, str | None, str | None]:
    """Get LLM configuration from environment.
    
    Returns:
        tuple: (model_name, api_base, api_key)
        - If GUM_LM_API_BASE is set: use Ollama with MODEL_NAME
        - Otherwise: use OpenAI with OPENAI_API_KEY and OPENAI_MODEL
    """
    gum_lm_api_base = os.getenv("GUM_LM_API_BASE")
    
    if gum_lm_api_base:
        # Use Ollama
        model_name = os.getenv("MODEL_NAME", "llama3.1:8b")
        api_key = os.getenv("GUM_LM_API_KEY")
        return model_name, gum_lm_api_base, api_key
    else:
        # Use OpenAI
        model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        api_key = os.getenv("OPENAI_API_KEY")
        return model_name, None, api_key

# ============================================================================
# Stateless Helper Functions (No Gum Instances)
# ============================================================================

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
    # Verify token belongs to the user making the request
    token_user = token.get("sub")
    if token_user != user:
        raise HTTPException(status_code=403, detail="Token does not match requested user")
    
    # Get user_id from token claims
    user_id = token.get("user_id")
    if not user_id:
        raise HTTPException(status_code=500, detail="user_id not found in token")
    
    # Fetch recent propositions directly from database (stateless)
    props = await _get_recent_propositions(user_id, limit=limit)
    return props

@app.on_event("startup")
async def _startup():
    global _background_task
    print("[STARTUP] FastAPI startup event triggered!")
    logger.info("API startup: starting background batch processor")
    _background_task = asyncio.create_task(_background_batch_processor())


@app.on_event("shutdown")
async def _shutdown():
    """Shutdown the background batch processor."""
    global _background_task
    logger.info("API shutdown: stopping background batch processor")
    
    # Cancel background task
    if _background_task:
        _background_task.cancel()
        try:
            await _background_task
        except asyncio.CancelledError:
            pass

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