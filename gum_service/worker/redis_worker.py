import os
import asyncio
from typing import Dict
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

from ..config.database import init_db
from ..prompts import PROPOSE_PROMPT, SIMILAR_PROMPT, REVISE_PROMPT
from ..services.proposition_service import process_observation_batch
from ..services.redis_service import RedisObservationService


BACKGROUND_WORKER_CONFIG = {
    "flush_interval_seconds": int(os.getenv("FLUSH_INTERVAL_SECONDS", "30")),
    "min_batch_size": int(os.getenv("MIN_BATCH_SIZE", "1")),
    "max_concurrent_processing": int(os.getenv("MAX_CONCURRENT_PROCESSING", "10")),
}

_background_task: asyncio.Task | None = None
_user_processing_locks: Dict[str, asyncio.Lock] = {}
_lock_creation_lock = asyncio.Lock()


def _get_llm_config() -> tuple[str, str | None, str | None]:
    """Get LLM configuration from environment.
    
    Returns:
        tuple: (model_name, api_base, api_key)
        - If GUM_LM_API_BASE is set: use Ollama with MODEL_NAME
        - Otherwise: use OpenAI with OPENAI_API_KEY and OPENAI_MODEL
    """
    gum_lm_api_base = os.getenv("GUM_LM_API_BASE")
    
    if gum_lm_api_base:
        model_name = os.getenv("MODEL_NAME", "llama3.1:8b")
        api_key = os.getenv("GUM_LM_API_KEY")
        return model_name, gum_lm_api_base, api_key
    else:
        model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        api_key = os.getenv("OPENAI_API_KEY")
        return model_name, None, api_key

async def _get_user_lock(username: str) -> asyncio.Lock:
    """Get or create a per-user lock for serialized observation processing."""
    async with _lock_creation_lock:
        if username not in _user_processing_locks:
            _user_processing_locks[username] = asyncio.Lock()
        return _user_processing_locks[username]

async def _background_batch_processor(redis_service: RedisObservationService):
    print("[BATCHER] Background batch processor STARTED!")
    
    """Background task to periodically process observations from Redis using stateless service.
    
    This task:
    1. Scans Redis for users with pending observations
    2. Processes observations with bounded concurrency (semaphore)
    3. Calls proposition_service.process_observation_batch() for each user
    4. Handles errors gracefully (logs + continues)
    5. No gum instance caching needed (stateless processing)
    """
    semaphore = asyncio.Semaphore(BACKGROUND_WORKER_CONFIG["max_concurrent_processing"])
    llm_model, api_base, api_key = _get_llm_config()
    
    if not api_key:
        print("No LLM API key configured. Please set either OPENAI_API_KEY or GUM_LM_API_KEY.")
        return
    
    # Initialize appropriate LLM client
    if api_base:
        llm_client = AsyncOpenAI(api_key=api_key, base_url=api_base)
    else:
        llm_client = AsyncOpenAI(api_key=api_key)
    
    while True:
        try:
            loop = asyncio.get_event_loop()
            pending_user_ids = await loop.run_in_executor(
                None,
                redis_service.get_all_pending_users,
            )
            if not pending_user_ids:
                print("No pending observations in Redis")
            else:
                print(f"Found {len(pending_user_ids)} users with pending observations")
                tasks = [
                    _process_user_observations_stateless(
                        user_id, redis_service, semaphore, llm_client, llm_model
                    )
                    for user_id in pending_user_ids
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, Exception):
                        print(f"Error processing user batch: {result}")

            # Sleep after processing (or if no pending users)
            await asyncio.sleep(BACKGROUND_WORKER_CONFIG["flush_interval_seconds"])
            
        except asyncio.CancelledError:
            print("Background batch processor shutting down")
            break
        except Exception as e:
            print(f"Error in background batch processor: {e}")

async def _process_user_observations_stateless(
    user_id: str,
    redis_service: RedisObservationService,
    semaphore: asyncio.Semaphore,
    llm_client: AsyncOpenAI,
    llm_model: str,
):
    """Process observations for a single user using stateless proposition service.
    
    Args:
        user_id: user_id from database (as string)
        semaphore: concurrency limiter
        llm_client: AsyncOpenAI client
        llm_model: LLM model name
    """
    async with semaphore:
        user_lock = await _get_user_lock(user_id)
        async with user_lock:
            try:
                min_batch_size = BACKGROUND_WORKER_CONFIG["min_batch_size"]
                loop = asyncio.get_event_loop()
                queue_size = await loop.run_in_executor(
                    None,
                    lambda: redis_service.get_queue_size(user_id),
                )
                if queue_size < min_batch_size:
                    print(f"User {user_id} has {queue_size} observations (< min {min_batch_size})")
                    return
                print(f"Processing {queue_size} observations for user {user_id}")
                observations = await loop.run_in_executor(
                    None,
                    lambda: redis_service.pop_observations(user_id, count=None),
                )
                if not observations:
                    return
                engine, Session = await init_db()
                try:
                    async with Session() as session:
                        async with session.begin():
                            # Fetch username from users table
                            from gum_service.models.user import User
                            user_obj = await session.get(User, user_id)
                            user_name = user_obj.username if user_obj else None
                            result = await process_observation_batch(
                                observations=observations,
                                user_id=user_id,
                                user_name=user_name,
                                model=llm_model,
                                llm_client=llm_client,
                                session=session,
                                propose_prompt=PROPOSE_PROMPT,
                                similar_prompt=SIMILAR_PROMPT,
                                revise_prompt=REVISE_PROMPT,
                            )
                            print(f"Processed observations for {user_id}: {result}")
                except Exception as e:
                    import traceback
                    print(f"Error calling proposition service for {user_id}: {e}\n{traceback.format_exc()}")
                    try:
                        await loop.run_in_executor(
                            None,
                            lambda: [
                                redis_service.add_observation(
                                    user_id,
                                    obs.get("observer_name", "unknown"),
                                    obs.get("content", ""),
                                    obs.get("content_type", "text"),
                                    observation_id=obs.get("id"),
                                )
                                for obs in observations
                            ],
                        )
                        print(f"Re-queued {len(observations)} observations for {user_id}")
                    except Exception as requeue_error:
                        print(f"Failed to re-queue observations: {requeue_error}")
                    raise
            except Exception as e:
                print(f"Error processing observations for {user_id}: {e}")
