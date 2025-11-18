from __future__ import annotations

import asyncio
import json
import logging
import os
from uuid import uuid4
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Callable, List
from .models import observation_proposition
import traceback

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import insert

from .db_utils import (
    filter_propositions,
    revise_propositions,
    get_related_observations,
    search_propositions_bm25,
    get_recent_propositions,
    get_recent_observations,
)

from .utils.llm_utils import generate_and_search

from .models import Observation, Proposition, init_db, User
from .observers import Observer
from .schemas import (
    PropositionItem,
    PropositionSchema,
    RelationSchema,
    Update,
    get_schema,
    AuditSchema
)
from gum_old.prompts.gum import AUDIT_PROMPT, PROPOSE_PROMPT, REVISE_PROMPT, SIMILAR_PROMPT

class gum:
    """A class for managing general user models.

    This class provides functionality for observing user behavior, generating and managing
    propositions about user behavior, and maintaining relationships between observations
    and propositions.

    Args:
        user_name (str): The name of the user being modeled.
        *observers (Observer): Variable number of observer instances to track user behavior.
        propose_prompt (str, optional): Custom prompt for proposition generation.
        similar_prompt (str, optional): Custom prompt for similarity analysis.
        revise_prompt (str, optional): Custom prompt for proposition revision.
        audit_prompt (str, optional): Custom prompt for auditing.
        data_directory (str, optional): Directory for storing data. Defaults to "~/.cache/gum".
        db_name (str, optional): Name of the database file. Defaults to "gum.db".

        verbosity (int, optional): Logging verbosity level. Defaults to logging.INFO.
        audit_enabled (bool, optional): Whether to enable auditing. Defaults to False.
    """

    def __init__(
        self,
        user_name: str,
        model: str,
        *observers: Observer,
        propose_prompt: str | None = None,
        similar_prompt: str | None = None,
        revise_prompt: str | None = None,
        audit_prompt: str | None = None,
        data_directory: str = "~/.cache/gum",
        db_name: str = "gum.db",
        verbosity: int = logging.INFO,
        audit_enabled: bool = False,
        api_base: str | None = None,
        api_key: str | None = None,
        min_batch_size: int = 5,
        max_batch_size: int = 50,
    ):
        # basic paths
        data_directory = os.path.expanduser(data_directory)
        os.makedirs(data_directory, exist_ok=True)

        # runtime
        self.user_name = user_name
        self.observers: list[Observer] = list(observers)
        self.model = model
        self.audit_enabled = audit_enabled

        # batching configuration
        self.min_batch_size = min_batch_size
        self.max_batch_size = max_batch_size

        # logging
        self.logger = logging.getLogger("gum")
        self.logger.setLevel(verbosity)
        if not self.logger.handlers:
            h = logging.StreamHandler()
            h.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
            self.logger.addHandler(h)

        # prompts
        self.propose_prompt = propose_prompt or PROPOSE_PROMPT
        self.similar_prompt = similar_prompt or SIMILAR_PROMPT
        self.revise_prompt = revise_prompt or REVISE_PROMPT
        self.audit_prompt = audit_prompt or AUDIT_PROMPT

        self.client = AsyncOpenAI(
            base_url=api_base or os.getenv("GUM_LM_API_BASE"), 
            api_key=api_key or os.getenv("GUM_LM_API_KEY") or os.getenv("OPENAI_API_KEY") or "None"
        )

        self.engine = None
        self.Session = None
        self._db_name        = db_name
        self._data_directory = data_directory
        self._user_id = None

        self._loop_task: asyncio.Task | None = None
        self._batch_processing_lock = asyncio.Lock()
        self.update_handlers: list[Callable[[Observer, Update], None]] = [self._default_handler]

    def start_update_loop(self):
        """Start the asynchronous update loop for processing observer updates."""
        if self._loop_task is None:
            self._loop_task = asyncio.create_task(self._update_loop())
            

    async def stop_update_loop(self):
        """Stop the asynchronous update loop and clean up resources."""
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None
            

    async def connect_db(self):
        """Initialize the database connection if not already connected."""
        if self.engine is None:
            self.engine, self.Session = await init_db(
                self._db_name, self._data_directory
            )

    async def __aenter__(self):
        """Async context manager entry point.
        
        Returns:
            gum: The instance of the gum class.
        """
        await self.connect_db()
        await self._ensure_user()
        self.start_update_loop()
        return self

    async def _ensure_user(self) -> None:
        """Create or fetch the user row for self.user_name and set self._user_id."""
        from sqlalchemy import select

        async with self._session() as session:
            res = await session.execute(
                select(User).where(User.username == self.user_name)
            )
            user = res.scalars().first()
            if user is None:
                user = User(username=self.user_name)
                session.add(user)
                await session.flush()
            self._user_id = user.id

    async def __aexit__(self, exc_type, exc, tb):
        """Async context manager exit point.
        
        Args:
            exc_type: The type of exception if any.
            exc: The exception instance if any.
            tb: The traceback if any.
        """
        await self.stop_update_loop()

        # stop observers
        for obs in self.observers:
            await obs.stop()

    async def _update_loop(self):
        """Efficiently wait for any observer to produce an Update and dispatch it.
        
        This method continuously monitors all observers for updates and processes them
        through the semaphore-guarded handler.
        """
        while True:
            gets = {
                asyncio.create_task(obs.update_queue.get()): obs
                for obs in self.observers
            }

            done, _ = await asyncio.wait(
                gets.keys(), return_when=asyncio.FIRST_COMPLETED
            )

            for fut in done:
                upd: Update = fut.result()
                obs = gets[fut]

                for handler in self.update_handlers:
                    asyncio.create_task(handler(obs, upd))


    async def _process_batch(self, batched_observations):
        if not getattr(self, '_user_id', None):
            self.logger.error("Cannot insert observations: self._user_id is not set!")
            return
        """Process a batch of observations together to reduce API calls."""
        self.logger.info(f"_process_batch called with {len(batched_observations)} observations")
        
        # Combine all observations into a single content for analysis
        combined_content = []
        observation_ids = []
        
        for obs in batched_observations:
            combined_content.append(f"[{obs['observer_name']}] {obs['content']}")
            observation_ids.append(obs['id'])
            
        combined_text = "\n\n".join(combined_content)
        self.logger.info(f"Combined text for propositions: {combined_text[:200]}...")
        
        # Create a combined update
        combined_update = Update(
            content=combined_text,
            content_type="input_text"
        )
        
        observations = []
        try:
            async with self._session() as session:
                # Deduplicate observations in batch before inserting
                seen = set()
                for obs in batched_observations:
                    key = (obs['observer_name'], self._user_id, obs['content'], obs['content_type'])
                    if key in seen:
                        continue
                    seen.add(key)
                    observation = Observation(
                        observer_name=obs['observer_name'],
                        user_id=self._user_id,
                        content=obs['content'],
                        content_type=obs['content_type'],
                    )
                    session.add(observation)
                    observations.append(observation)
                await session.flush()
                self.logger.info(f"Created {len(observations)} unique observations in database")

                # Process the combined content
                self.logger.info("Starting proposition generation...")
                pool = await generate_and_search(self.logger, 
                                                 self.propose_prompt, 
                                                 self.user_name, 
                                                 self.model, 
                                                 self.client, 
                                                 self._user_id, 
                                                 session, 
                                                 combined_update)
                self.logger.info(f"Generated {len(pool)} propositions in pool")

                identical, similar, different = await filter_propositions(pool, self.similar_prompt, get_schema, RelationSchema, self.client, self.model)
                self.logger.info(f"Filtered propositions: identical={len(identical)}, similar={len(similar)}, different={len(different)}")

                self.logger.info("Applying proposition updates for batch...")
                await self._handle_identical(session, identical, observations)
                await self._handle_similar(session, similar, observations)
                await self._handle_different(session, different, observations)

                await session.commit()
                self.logger.info(f"Committed batch to database. Completed processing batch of {len(batched_observations)} observations")

        except Exception as e:
            self.logger.error(f"Error processing batch: {e}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            self.logger.error(f"Batch size: {len(batched_observations)}")
            if batched_observations:
                self.logger.error(f"First observation type: {type(batched_observations[0])}")
                self.logger.error(f"First observation: {batched_observations[0]}")
            # Only re-queue observations that were not successfully inserted
            inserted_keys = set((obs.observer_name, obs.user_id, obs.content, obs.content_type) for obs in observations)
            for obs in batched_observations:
                key = (obs['observer_name'], self._user_id, obs['content'], obs['content_type'])
                if key not in inserted_keys:
                    # NOTE: Re-queueing would happen via Redis in server mode
                    self.logger.warning(f"Observation failed to insert and was not re-queued: {obs['id']}")

    async def process_redis_batch(self, redis_service, count: int | None = None) -> dict:
        """Pop observations for this instance from Redis and process them.

        This method will:
        - ensure this gum instance has a user_id
        - atomically pop observations from Redis (via the provided service)
        - invoke the internal _process_batch(...) routine to persist observations

        On processing failure this method will attempt to re-queue the observations
        back into Redis to avoid data loss.

        Args:
            redis_service: An instance implementing `pop_observations(username, user_id, count)` and `add_observation(...)`.
            count: Optional max number of observations to pop/process.

        Returns:
            dict: {"processed": <n>} number of observations processed
        """
        # ensure we have a cached user id
        if not getattr(self, "_user_id", None):
            await self._ensure_user()

        loop = asyncio.get_event_loop()
        try:
            observations = await loop.run_in_executor(None, lambda: redis_service.pop_observations(self.user_name, self._user_id, count))
        except Exception as e:
            self.logger.error(f"Failed to fetch observations from Redis for {self.user_name}:{self._user_id}: {e}")
            raise

        if not observations:
            return {"processed": 0}

        try:
            await self._process_batch(observations)
            return {"processed": len(observations)}
        except Exception as e:
            self.logger.error(f"Error processing Redis batch for {self.user_name}:{self._user_id}: {e}")
            # attempt to re-queue observations back to Redis to avoid data loss
            try:
                def _requeue():
                    for obs in observations:
                        redis_service.add_observation(
                            self.user_name,
                            self._user_id,
                            obs.get("observer_name", "unknown"),
                            obs.get("content", ""),
                            obs.get("content_type", "text"),
                            observation_id=obs.get("id"),
                        )
                await loop.run_in_executor(None, _requeue)
                self.logger.info(f"Re-queued {len(observations)} observations back to Redis for {self.user_name}")
            except Exception as re:
                self.logger.error(f"Failed to re-queue observations after processing failure: {re}")
            raise

    async def _handle_identical(
        self, session, identical: list[Proposition], observations: list[Observation]
    ) -> None:
        for p in identical:
            for obs in observations:
                await self._attach_obs_if_missing(p, obs, session)

    async def _handle_similar(
        self,
        session: AsyncSession,
        similar: list[Proposition],
        observations: list[Observation],
    ) -> None:

        if not similar:
            return

        # Collect all observations from similar propositions
        rel_obs = {
            o
            for p in similar
            for o in await get_related_observations(session, p.id)
        }
        # Add all the batched observations
        rel_obs.update(observations)

        # Generate revised propositions
        revised_items = await revise_propositions(list(rel_obs), similar, self.revise_prompt, get_schema, PropositionSchema, self.client, self.model)
        
        # Delete all old similar propositions
        for prop in similar:
            await session.delete(prop)
        
        # Create new propositions to replace them
        revision_group = str(uuid4())
        for item in revised_items:
            new_prop = Proposition(
                text=item["proposition"],
                reasoning=item["reasoning"],
                confidence=item.get("confidence"),
                decay=item.get("decay"),
                version=1,  # Start fresh with version 1
                revision_group=revision_group,
                observations=rel_obs,
            )
            session.add(new_prop)

        await session.flush()

    async def _handle_different(
        self, session, different: list[Proposition], observations: list[Observation]
    ) -> None:
        for p in different:
            for obs in observations:
                await self._attach_obs_if_missing(p, obs, session)

    async def _handle_audit(self, obs: Observation) -> bool:
        if not self.audit_enabled:
            return False

        hits = await self.query(obs.content, limit=10, mode="OR")

        if not hits:
            past_interaction = "*None*"
        else:
            ctx_chunks: list[str] = []
            async with self._session() as session:
                for prop, score in hits:
                    chunk = [f"• {prop.text}"]
                    if prop.reasoning:
                        chunk.append(f"  Reasoning: {prop.reasoning}")
                    if prop.confidence is not None:
                        chunk.append(f"  Confidence: {prop.confidence}")
                    chunk.append(f"  Relevance Score: {score:.2f}")

                    obs_list = await get_related_observations(session, prop.id)
                    if obs_list:
                        chunk.append("  Supporting Observations:")
                        for rel_obs in obs_list:
                            preview = rel_obs.content.replace("\n", " ")[:120]
                            chunk.append(f"    - [{rel_obs.observer_name}] {preview}")

                    ctx_chunks.append("\n".join(chunk))

            past_interaction = "\n\n".join(ctx_chunks)

        prompt = (
            self.audit_prompt
            .replace("{past_interaction}", past_interaction)
            .replace("{user_input}", obs.content)
            .replace("{user_name}", self.user_name)
        )

        rsp = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format=get_schema(AuditSchema.model_json_schema()),
            temperature=0.0,
        )
        decision = json.loads(rsp.choices[0].message.content)

        if not decision["transmit_data"]:
            self.logger.warning(
                "Audit blocked transmission (data_type=%s, subject=%s)",
                decision["data_type"],
                decision["subject"],
            )
            return True

        return False

    async def _default_handler(self, observer: Observer, update: Update) -> None:
        self.logger.info(f"Processing update from {observer.name}")
        
        # NOTE: Observation queueing now happens at the server level via Redis.
        # This handler is kept for potential future use but doesn't queue observations anymore.

    @asynccontextmanager
    async def _session(self):
        async with self.Session() as s:
            async with s.begin():
                yield s

    @staticmethod
    async def _attach_obs_if_missing(prop: Proposition, obs: Observation, session):
        await session.execute(
            insert(observation_proposition)
            .prefix_with("OR IGNORE")
            .values(observation_id=obs.id, proposition_id=prop.id)
        )
        prop.updated_at = datetime.now(timezone.utc)

    def add_observer(self, observer: Observer):
        """Add an observer to track user behavior.
        
        Args:
            observer (Observer): The observer to add.
        """
        self.observers.append(observer)

    def remove_observer(self, observer: Observer):
        """Remove an observer from tracking.
        
        Args:
            observer (Observer): The observer to remove.
        """
        if observer in self.observers:
            self.observers.remove(observer)

    def register_update_handler(self, fn: Callable[[Observer, Update], None]):
        """Register a custom update handler function.
        
        Args:
            fn (Callable[[Observer, Update], None]): The handler function to register.
        """
        self.update_handlers.append(fn)

    async def query(
        self,
        user_query: str,
        *,
        limit: int = 3,
        mode: str = "OR",
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[tuple[Proposition, float]]:
        """Query the database for propositions matching the user query.
        
        Args:
            user_query (str): The query string to search for.
            limit (int, optional): Maximum number of results to return. Defaults to 3.
            mode (str, optional): Search mode ("OR" or "AND"). Defaults to "OR".
            start_time (datetime, optional): Start time for filtering results. Defaults to None.
            end_time (datetime, optional): End time for filtering results. Defaults to None.
            
        Returns:
            list[tuple[Proposition, float]]: List of tuples containing propositions and their relevance scores.
        """
        async with self._session() as session:
            return await search_propositions_bm25(
                session,
                user_query,
                user_id=self._user_id,
                limit=limit,
                mode=mode,
                start_time=start_time,
                end_time=end_time,
            )

    async def recent(
        self,
        *,
        limit: int = 10,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        include_observations: bool = False,
    ) -> list[Proposition]:
        """Return the most recent propositions ordered by created_at descending."""
        async with self._session() as session:
            return await get_recent_propositions(
                session,
                limit=limit,
                user_id=self._user_id,
                start_time=start_time,
                end_time=end_time,
                include_observations=include_observations,
            )

    async def recent_observations(
        self,
        *,
        limit: int = 10,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[Observation]:
        """Return the most recent observations ordered by created_at descending."""
        async with self._session() as session:
            return await get_recent_observations(
                session,
                limit=limit,
                user_id=self._user_id,
                start_time=start_time,
                end_time=end_time,
            )
