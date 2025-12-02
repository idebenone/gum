from __future__ import annotations
import json
import math
import re
from datetime import datetime, timezone
from typing import List

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from sqlalchemy import (
    MetaData,
    Table,
    select,
    literal_column,
    text,
    func,
)

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import (
    Observation,
    Proposition,
    observation_proposition,
)

# Constants
K_DECAY = 2.0      # decay rate for recency adjustment
LAMBDA = 0.5       # trade-off for MMR

async def filter_propositions(rel_props: list[Proposition], similar_prompt, get_schema, RelationSchema, client, model) -> tuple[list[Proposition], list[Proposition], list[Proposition]]:
    """Filter propositions into identical, similar, and unrelated groups."""
    if not rel_props:
        return [], [], []

    payload = [
        {"id": p.id, "proposition": p.text, "reasoning": p.reasoning or ""}
        for p in rel_props
    ]
    blocks = [
        f"[id={p['id']}] {p['proposition']}\n    Reasoning: {p['reasoning']}"
        for p in payload
    ]
    body = "\n\n".join(blocks)
    prompt_text = similar_prompt.replace("{body}", body)

    rsp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt_text}],
        response_format=get_schema(RelationSchema.model_json_schema()),
    )
    data = RelationSchema.model_validate_json(rsp.choices[0].message.content)

    id_to_prop = {p.id: p for p in rel_props}
    ident, sim, unrel = set(), set(), set()
    for r in data.relations:
        if r.label == "IDENTICAL":
            ident.add(r.source)
            ident.update(r.target or [])
        elif r.label == "SIMILAR":
            sim.add(r.source)
            sim.update(r.target or [])
        else:
            unrel.add(r.source)
    valid_ids = set(id_to_prop.keys())
    ident &= valid_ids
    sim &= valid_ids
    unrel &= valid_ids
    return (
        [id_to_prop[i] for i in ident],
        [id_to_prop[i] for i in sim - ident],
        [id_to_prop[i] for i in unrel - ident - sim],
    )

async def revise_propositions(related_obs: list[Observation], similar_cluster: list[Proposition], revise_prompt, get_schema, PropositionSchema, client, model):
    """Revise propositions based on related observations and similar propositions."""
    blocks = [
        f"Proposition {idx}: {p.text}\nReasoning: {p.reasoning}"
        for idx, p in enumerate(similar_cluster, 1)
    ]
    if related_obs:
        blocks.append("\nSupporting observations:")
        blocks.extend(f"- {o.content}" for o in related_obs[:10])
    body = "\n".join(blocks)
    prompt = revise_prompt.replace("{body}", body)
    rsp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format=get_schema(PropositionSchema.model_json_schema()),
    )
    return json.loads(rsp.choices[0].message.content)["propositions"]

def build_fts_query(raw: str, mode: str = "OR") -> str:
    tokens = re.findall(r"\w+", raw.lower())
    if not tokens:
        return ""
    if mode == "PHRASE":
        return f'"{" ".join(tokens)}"'
    elif mode == "OR":
        return " OR ".join(tokens)
    else:  # implicit AND
        return " ".join(tokens)

async def search_propositions_bm25(
    session: AsyncSession,
    user_query: str,
    *,
    user_id: int | None = None,
    limit: int = 3,
    mode: str = "OR",
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    include_observations: bool = True,
    enable_decay: bool = True,
    enable_mmr: bool = True,
) -> list[tuple["Proposition", float]]:

    q = build_fts_query(user_query, mode)
    has_query = bool(q)

    # --------------------------------------------------------
    # 1  Build candidate list
    # --------------------------------------------------------
    candidate_pool = limit * 10 if enable_mmr else limit

    if has_query:
        # Postgres FTS for propositions
        prop_fts = func.to_tsvector('english', Proposition.text + ' ' + Proposition.reasoning)
        prop_query = func.plainto_tsquery('english', q)
        prop_score = func.ts_rank_cd(prop_fts, prop_query).label('score')
        sub_p = (
            select(Proposition.id.label("pid"), prop_score)
            .where(prop_fts.op('@@')(prop_query))
        )
        if user_id is not None:
            sub_p = sub_p.where(Proposition.user_id == user_id)

        if include_observations:
            # Postgres FTS for observations
            obs_fts = func.to_tsvector('english', Observation.content + ' ' + Observation.observer_name)
            obs_query = func.plainto_tsquery('english', q)
            obs_score = func.ts_rank_cd(obs_fts, obs_query).label('score')
            sub_o = (
                select(observation_proposition.c.proposition_id.label("pid"), obs_score)
                .select_from(
                    Observation.__table__
                    .join(
                        observation_proposition,
                        observation_proposition.c.observation_id == Observation.id,
                    )
                )
                .where(obs_fts.op('@@')(obs_query))
            )
            if user_id is not None:
                sub_o = sub_o.where(Observation.user_id == user_id)
            union_sub = sub_p.union_all(sub_o).subquery()
            best_scores = (
                select(
                    union_sub.c.pid,
                    func.min(union_sub.c.score).label("score"),
                )
                .group_by(union_sub.c.pid)
                .subquery()
            )
        else:
            best_scores = (
                select(
                    Proposition.id.label("pid"),
                    prop_score,
                )
                .where(prop_fts.op('@@')(prop_query))
                .subquery()
            )
        stmt = (
            select(Proposition, best_scores.c.score)
            .join(best_scores, best_scores.c.pid == Proposition.id)
            .order_by(best_scores.c.score.desc())  # highest→best
        )
    else:
        # --- 1-b  No user query ------------------------------
        stmt = (
            select(Proposition, literal_column("0.0").label("bm25"))
            .order_by(Proposition.created_at.desc())
        )

    # --------------------------------------------------------
    # 2  Time filtering & eager-load
    # --------------------------------------------------------
    if end_time is None:
        end_time = datetime.now(timezone.utc)
    if start_time is not None and start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    if start_time is not None:
        stmt = stmt.where(Proposition.created_at >= start_time)
    stmt = stmt.where(Proposition.created_at <= end_time)

    if user_id is not None:
        stmt = stmt.where(Proposition.user_id == user_id)

    if include_observations:
        stmt = stmt.options(selectinload(Proposition.observations))

    stmt = stmt.limit(candidate_pool)

   # --------------------------------------------------------
    # 3  Execute & score
    # --------------------------------------------------------
    bind = {"q": q} if has_query else {}
    rows = (await session.execute(stmt, bind)).all()
    if not rows:
        return []

    # --- 3-a. Calculate initial scores ---
    initial_scores: list[float] = []
    now = datetime.now(timezone.utc)
    for prop, raw_score in rows:
        relevance_score = -raw_score if has_query else 0.0
        gamma = 0.0
        if enable_decay:
            dt = prop.created_at.replace(tzinfo=timezone.utc)
            age_days = max((now - dt).total_seconds() / 86_400, 0.0)
            alpha = prop.decay if prop.decay is not None else 0.0
            gamma = -alpha * K_DECAY * age_days

        score = relevance_score * math.exp(gamma)
        initial_scores.append(score)

    final_scores_np = np.array(initial_scores)
    min_score = np.min(final_scores_np)
    max_score = np.max(final_scores_np)
    
    if max_score > min_score:
        final_scores_np = (final_scores_np - min_score) / (max_score - min_score)
    else:
        final_scores_np = np.full_like(final_scores_np, 0.5)

    final_scores = final_scores_np.tolist()

    if enable_mmr and len(rows) > 1:
        docs: list[str] = []
        for p, _ in rows:
            doc_parts = [p.text, p.reasoning]
            if include_observations and p.observations:
                obs_concat = " ".join(o.content for o in list(p.observations)[:10])
                doc_parts.append(obs_concat)
            docs.append(" ".join(doc_parts))

        vecs = TfidfVectorizer().fit_transform(docs)
        
        selected_idxs = []
        mmr_scores = np.array(final_scores)

        while len(selected_idxs) < min(limit, len(rows)):
            if not selected_idxs:
                idx = int(np.argmax(mmr_scores))
            else:
                sims = cosine_similarity(vecs, vecs[selected_idxs]).max(axis=1)
                mmr = LAMBDA * mmr_scores - (1 - LAMBDA) * sims
                mmr[selected_idxs] = -np.inf 
                idx = int(np.argmax(mmr))

            selected_idxs.append(idx)
    else:
        idxs = np.argsort(final_scores)[::-1][:limit]
        selected_idxs = idxs.tolist()

    result = [(rows[i][0], final_scores[i]) for i in selected_idxs]    
    return result

async def get_related_observations(
    session: AsyncSession,
    proposition_id: int,
    *,  # Force keyword arguments for optional parameters
    limit: int = 5,
) -> List[Observation]:

    stmt = (
        select(Observation)
        .join(observation_proposition)
        .join(Proposition)
        .where(Proposition.id == proposition_id)
        .order_by(Observation.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()

async def get_recent_propositions(
    session: AsyncSession,
    *,
    limit: int = 10,
    user_id: int | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    include_observations: bool = False,
) -> List[Proposition]:
    """Fetch the most recent propositions ordered by created_at desc.

    Args:
        session: Active async DB session
        limit: Max number of propositions to return
        start_time: Optional lower bound for created_at
        end_time: Optional upper bound for created_at (defaults to now)
        include_observations: Whether to eager-load related observations

    Returns:
        List[Proposition]: Most recent propositions
    """

    if end_time is None:
        end_time = datetime.now(timezone.utc)
    if start_time is not None and start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    stmt = (
        select(Proposition)
        .where(Proposition.created_at <= end_time)
        .order_by(Proposition.created_at.desc())
        .limit(limit)
    )
    if start_time is not None:
        stmt = stmt.where(Proposition.created_at >= start_time)
    if user_id is not None:
        stmt = stmt.where(Proposition.user_id == user_id)
    if include_observations:
        stmt = stmt.options(selectinload(Proposition.observations))

    result = await session.execute(stmt)
    return result.scalars().all()

async def get_recent_observations(
    session: AsyncSession,
    *,
    limit: int = 10,
    user_id: int | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> List[Observation]:
    """Fetch the most recent observations ordered by created_at desc."""
    if end_time is None:
        end_time = datetime.now(timezone.utc)
    if start_time is not None and start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    stmt = (
        select(Observation)
        .where(Observation.created_at <= end_time)
        .order_by(Observation.created_at.desc())
        .limit(limit)
    )
    if start_time is not None:
        stmt = stmt.where(Observation.created_at >= start_time)
    if user_id is not None:
        stmt = stmt.where(Observation.user_id == user_id)

    result = await session.execute(stmt)
    return result.scalars().all()