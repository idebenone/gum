import json
from uuid import uuid4
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from .db_utils import search_propositions_bm25
from ..schemas.gum_schemas import PropositionItem, PropositionSchema, Update, get_schema
from ..models import Proposition
from logging import Logger

async def construct_propositions(
        logger: Logger,
        propose_prompt: str, 
        user_name: str, 
        model: str, 
        client: AsyncOpenAI, 
        update: Update
    ) -> list[PropositionItem]:
    """Generate propositions from an update.
        
    Args:
        update (Update): The update to generate propositions from.
            
    Returns:
        list[PropositionItem]: List of generated propositions.
    """
    logger.info(f"Calling LLM to generate propositions for content: {update.content[:100]}...")
    prompt = (
        propose_prompt.replace("{user_name}", user_name)
        .replace("{inputs}", update.content)
    )
    logger.debug(f"Proposition prompt: {prompt[:200]}...")

    schema = PropositionSchema.model_json_schema()
    logger.info(f"Making API call to {model} for proposition generation...")
    rsp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format=get_schema(schema),
    )
        
    result = json.loads(rsp.choices[0].message.content)["propositions"]
    logger.info(f"Generated {len(result)} propositions from LLM")
    return result
        
async def generate_and_search(
    logger: Logger,
    propose_prompt: str,
    user_name: str,
    model: str,
    client: AsyncOpenAI,
    user_id: str,
    session: AsyncSession, 
    update: Update
) -> list[Proposition]:

    drafts_raw = await construct_propositions(
        logger,
        propose_prompt,
        user_name,
        model,
        client,
        update
    )
    drafts: list[Proposition] = []
    pool: dict[int, Proposition] = {}

    for itm in drafts_raw:
        draft = Proposition(
            text=itm["proposition"],
            reasoning=itm["reasoning"],
            user_id=user_id,
            confidence=itm.get("confidence"),
            decay=itm.get("decay"),
            revision_group=str(uuid4()),
            version=1,
        )
        drafts.append(draft)

        with session.no_autoflush:
            hits = await search_propositions_bm25(
                session, f"{draft.text}\n{draft.reasoning}", user_id=user_id, mode="OR",
                include_observations=False,
                enable_mmr=False,
                enable_decay=True
            )
                
        for prop, _score in hits:
            pool[prop.id] = prop

    session.add_all(drafts)
    await session.flush()

    for draft in drafts:
        pool[draft.id] = draft

    return list(pool.values())
