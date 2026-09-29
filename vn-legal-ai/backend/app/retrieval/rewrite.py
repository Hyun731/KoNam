"""질의 재작성: 한국어·베트남어 질문 → 베트남 법령 용어로 된 검색 질의."""

import logging
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app import llm
from app.core.glossary import glossary_text
from app.core.lang import Lang, today_vn

log = logging.getLogger(__name__)

Domain = Literal[
    "hop_dong", "dan_su", "lao_dong", "nha_o", "dat_dai", "doanh_nghiep", "dau_tu", "thuong_mai", "tranh_chap", "khac"
]


class RewrittenQuery(BaseModel):
    queries_vi: list[str] = Field(description="1-3 search queries in Vietnamese legal terminology")
    domains: list[Domain]
    as_of: str | None = Field(description="ISO date (YYYY-MM-DD) if the user asks about a specific date, else null")
    standalone_question: str = Field(description="The user's question rewritten to be self-contained, same language")


INSTRUCTIONS = f"""You turn a user's question about Vietnamese road traffic law (fines, licence points, driving licences, vehicle registration, accidents, insurance) into search queries for a database of Vietnamese traffic laws, decrees and circulars.
- Write queries_vi in formal Vietnamese legal terminology as used in Vietnamese statutes, not colloquial words.
- Produce 1-3 queries that cover different angles (the right, the obligation, the sanction/limit).
- If earlier conversation turns are given, resolve pronouns and follow-ups into a standalone question.
- Pick domains from the allowed list; use "khac" if unsure.
English → Vietnamese traffic-law glossary:
{glossary_text()}"""


async def rewrite_query(question: str, lang: Lang, history: list[dict]) -> RewrittenQuery:
    try:
        return await llm.parse(
            RewrittenQuery,
            INSTRUCTIONS,
            [*history[-6:], {"role": "user", "content": question}],
            fast=True,
        )
    except Exception:  # LLM 실패 시 원문 그대로 검색
        log.exception("질의 재작성 실패, 원문으로 검색")
        return RewrittenQuery(queries_vi=[question], domains=[], as_of=None, standalone_question=question)


def resolve_as_of(q: RewrittenQuery, explicit: date | None) -> date:
    if explicit:
        return explicit
    if q.as_of:
        try:
            return date.fromisoformat(q.as_of)
        except ValueError:
            pass
    return today_vn()
