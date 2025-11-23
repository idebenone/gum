"""Stateless proposition generation and batch processing service.

This module extracts core business logic from gum.core._process_batch into
a pure, reusable service that can be called by workers, CLI, API, or any
other context without requiring a gum instance.

The main entrypoint is `process_observation_batch(...)` which:
1. Accepts a list of observations (dicts)
2. Inserts them into the DB
3. Calls LLM to generate propositions
4. Filters and applies proposition updates
5. Returns a result dict with counts and status
"""

import logging

import json
from uuid import uuid4
from typing import Dict, Any, List
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import insert
from openai import AsyncOpenAI

from ..models import Observation, Proposition, observation_proposition
from ..utils.db_utils import (
    filter_propositions,
    revise_propositions,
    get_related_observations,
)
from ..schemas.gum_schemas import (
    PropositionSchema,
    RelationSchema,
    Update,
    get_schema,
)
from ..utils.llm_utils import generate_and_search
from ..prompts.gum_prompts import AUDIT_PROMPT

logger = logging.getLogger("gum.api.proposition_service")


class PropositionProcessingError(Exception):
    """Raised when batch processing fails and observations should be requeued."""
    pass


async def process_observation_batch(
    observations: List[Dict[str, Any]],
    user_id: int,
    user_name: str,
    model: str,
    llm_client: AsyncOpenAI,
    session: AsyncSession,
    propose_prompt: str,
    similar_prompt: str,
    revise_prompt: str,
) -> Dict[str, Any]:
    """Process a batch of observations and generate/update propositions.

    This is a pure, stateless function that:
    - Deduplicates and inserts observations into the DB
    - Generates new propositions using LLM
    - Filters (identical/similar/different) existing propositions
    - Applies updates (create/attach/delete)
    - Commits DB transaction

    Args:
        observations: List of observation dicts with keys:
            {id, observer_name, content, content_type, [user_id], [timestamp]}
        user_id: User ID (from DB User table)
        user_name: Username for logging and prompt injection
        model: LLM model name (e.g., "gpt-4o-mini")
        llm_client: AsyncOpenAI client instance
        session: SQLAlchemy async session (must support commit/rollback)
        propose_prompt: Prompt template for proposition generation
        similar_prompt: Prompt template for similarity checking
        revise_prompt: Prompt template for revision

    Returns:
        dict with keys:
        - status: "success" or "error"
        - observations_inserted: count
        - propositions_generated: count
        - propositions_identical: count
        - propositions_similar: count
        - propositions_different: count
        - error: (if status="error") error message

    Raises:
        PropositionProcessingError: on DB or LLM errors (caller should requeue observations)
    """
    logger.info(f"Processing batch of {len(observations)} observations for user {user_name}:{user_id}")

    # Combine observations for analysis
    combined_content = []
    observation_ids = []

    for obs in observations:
        combined_content.append(f"[{obs['observer_name']}] {obs['content']}")
        observation_ids.append(obs['id'])

    combined_text = "\n\n".join(combined_content)
    logger.info(f"Combined text for propositions: {combined_text[:200]}...")

    # Create a combined update for LLM
    combined_update = Update(
        content=combined_text,
        content_type="input_text"
    )

    inserted_observations = []
    try:
        # Deduplicate observations in batch before inserting
        seen = set()
        for obs in observations:
            key = (obs['observer_name'], user_id, obs['content'], obs['content_type'])
            if key in seen:
                logger.debug(f"Skipping duplicate observation: {obs['id']}")
                continue
            seen.add(key)

            # --- AUDIT FUNCTIONALITY ---
            # Build audit prompt
            audit_prompt = AUDIT_PROMPT.replace("{user_name}", user_name)
            audit_prompt = audit_prompt.replace("{user_input}", obs['content'])
            # For now, we use empty past_interaction
            audit_prompt = audit_prompt.replace("{past_interaction}", "")

            audit_rsp = await llm_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": audit_prompt}],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            audit_decision = None
            try:
                audit_decision = json.loads(audit_rsp.choices[0].message.content)
            except Exception as e:
                logger.error(f"Audit LLM response parsing failed: {e}")
                audit_decision = {"transmit_data": True}

            if not audit_decision.get("transmit_data", True):
                logger.warning(f"Audit blocked transmission for observation {obs['id']} (observer={obs['observer_name']})")
                continue

            observation = Observation(
                observer_name=obs['observer_name'],
                user_id=user_id,
                content=obs['content'],
                content_type=obs['content_type'],
            )
            session.add(observation)
            inserted_observations.append(observation)

        await session.flush()
        logger.info(f"Inserted {len(inserted_observations)} observations into DB")

        # Generate propositions using LLM
        logger.info("Starting proposition generation via LLM...")
        proposition_pool = await generate_and_search(
            logger,
            propose_prompt,
            user_name,
            model,
            llm_client,
            user_id,
            session,
            combined_update,
        )
        logger.info(f"Generated {len(proposition_pool)} propositions from LLM")

        # Filter propositions into categories
        identical, similar, different = await filter_propositions(
            proposition_pool,
            similar_prompt,
            get_schema,
            RelationSchema,
            llm_client,
            model,
        )
        logger.info(
            f"Filtered propositions: identical={len(identical)}, "
            f"similar={len(similar)}, different={len(different)}"
        )

        # Apply proposition updates
        logger.info("Applying proposition updates...")
        await _handle_identical(session, identical, inserted_observations)
        await _handle_similar(session, similar, inserted_observations, revise_prompt, llm_client, model, user_id)
        await _handle_different(session, different, inserted_observations)

        await session.commit()
        logger.info(
            f"Successfully committed batch: {len(inserted_observations)} observations, "
            f"{len(proposition_pool)} propositions"
        )

        return {
            "status": "success",
            "observations_inserted": len(inserted_observations),
            "propositions_generated": len(proposition_pool),
            "propositions_identical": len(identical),
            "propositions_similar": len(similar),
            "propositions_different": len(different),
        }

    except Exception as e:
        logger.error(f"Error processing batch: {e}", exc_info=True)
        await session.rollback()
        raise PropositionProcessingError(f"Batch processing failed: {str(e)}") from e


async def _handle_identical(
    session: AsyncSession, identical: List[Proposition], observations: List[Observation]
) -> None:
    """Attach observations to identical propositions."""
    for p in identical:
        for obs in observations:
            await _attach_obs_if_missing(p, obs, session)


async def _handle_similar(
    session: AsyncSession,
    similar: List[Proposition],
    observations: List[Observation],
    revise_prompt: str,
    llm_client: AsyncOpenAI,
    model: str,
    user_id: str,
) -> None:
    """Revise similar propositions and attach observations."""
    if not similar:
        return

    # Collect all related observations
    rel_obs = {
        o
        for p in similar
        for o in await get_related_observations(session, p.id)
    }
    rel_obs.update(observations)

    # Generate revised propositions
    revised_items = await revise_propositions(
        list(rel_obs), similar, revise_prompt, get_schema, PropositionSchema, llm_client, model
    )

    # Delete old similar propositions
    for prop in similar:
        await session.delete(prop)

    # Create new revised propositions
    revision_group = str(uuid4())
    for item in revised_items:
        new_prop = Proposition(
            text=item["proposition"],
            reasoning=item["reasoning"],
            confidence=item.get("confidence"),
            decay=item.get("decay"),
            version=1,
            revision_group=revision_group,
            observations=rel_obs,
            user_id=user_id,
        )
        session.add(new_prop)

    await session.flush()


async def _handle_different(
    session: AsyncSession, different: List[Proposition], observations: List[Observation]
) -> None:
    """Attach observations to different propositions."""
    for p in different:
        for obs in observations:
            await _attach_obs_if_missing(p, obs, session)


@staticmethod
async def _attach_obs_if_missing(prop: Proposition, obs: Observation, session):
    """Attach observation to proposition if not already related."""
    await session.execute(
        insert(observation_proposition)
        .prefix_with("OR IGNORE")
        .values(observation_id=obs.id, proposition_id=prop.id)
    )
    prop.updated_at = datetime.now(timezone.utc)


# Alias for backward compatibility with earlier design discussions
process_batch = process_observation_batch
