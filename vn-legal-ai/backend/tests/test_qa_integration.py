"""질의응답 전체 흐름 통합 테스트. LLM은 가짜로 바꾸고, DB는 샘플 법령이 적재된 로컬 Postgres를 쓴다.

준비: alembic upgrade head && python -m ingest load --samples
DB에 접속할 수 없거나 샘플이 없으면 건너뛴다.
"""

import asyncio

import pytest
from sqlalchemy import text

from app import llm
from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.generation.answer import Citation, LegalAnswer
from app.retrieval.rewrite import RewrittenQuery
from app.schemas.chat import ChatRequest
from app.services.qa import answer_stream


async def _samples_loaded() -> bool:
    try:
        async with SessionLocal() as s:
            n = (await s.execute(text("SELECT count(*) FROM legal_documents WHERE is_sample"))).scalar_one()
            return n > 0
    except Exception:
        return False


def _run(coro):
    async def wrapper():
        try:
            return await coro
        finally:
            await engine.dispose()

    return asyncio.run(wrapper())


@pytest.fixture
def fake_llm(monkeypatch):
    calls: list[str] = []

    async def fake_parse(output_type, instructions, messages, *, fast=False):
        calls.append(output_type.__name__)
        if output_type is RewrittenQuery:
            return RewrittenQuery(
                queries_vi=["mức tiền đặt cọc tối đa thuê nhà"],
                domains=["nha_o"],
                as_of=None,
                standalone_question="집주인이 받을 수 있는 보증금 한도는?",
            )
        bad_first = len([c for c in calls if c == "LegalAnswer"]) == 1
        return LegalAnswer(
            answer="보증금(tiền đặt cọc)은 3개월치 임대료를 넘을 수 없습니다 [1][2].",
            citations=[
                Citation(
                    provision_id="02/2024/NĐ-TEST:D2",
                    quote_vi="không vượt quá 03 tháng tiền thuê",
                    quote_translation="3개월치 임대료를 넘지 않는다",
                ),
                Citation(
                    provision_id="01/2024/QH-TEST:D4:K2",
                    # 첫 응답은 원문에 없는 문장을 인용 → 재생성 유도
                    quote_vi="tối đa 6 tháng" if bad_first else "Mức tiền đặt cọc không vượt quá mức quy định",
                    quote_translation="…",
                ),
            ],
            confidence="high",
            needs_lawyer=False,
            follow_up_questions=[],
        )

    async def fake_embed(texts):
        raise RuntimeError("no key in tests")

    async def fake_parse_stream(output_type, instructions, messages, on_text, **_):
        result = await fake_parse(output_type, instructions, messages)
        await on_text(result.answer[:10])
        await on_text(result.answer)
        return result

    monkeypatch.setattr(llm, "parse", fake_parse)
    monkeypatch.setattr(llm, "parse_stream", fake_parse_stream)
    monkeypatch.setattr("app.retrieval.hybrid.embed_texts", fake_embed)
    monkeypatch.setattr(get_settings(), "include_samples", True)
    monkeypatch.setattr(get_settings(), "llm_fake", False)
    # 실제 교통 법령도 함께 적재돼 있으므로 샘플 조문이 밀리지 않게 후보를 넉넉히 둔다
    monkeypatch.setattr(get_settings(), "context_k", 40)
    return calls


def test_answer_flow_with_retry(fake_llm):
    async def go():
        if not await _samples_loaded():
            pytest.skip("로컬 DB에 샘플 법령이 없음")
        async with SessionLocal() as s:
            return [ev async for ev in answer_stream(s, ChatRequest(message="보증금은 최대 얼마까지 받을 수 있나요?"))]

    events = _run(go())
    stages = [e["data"]["stage"] for e in events if e["event"] == "stage"]
    assert stages == ["rewriting", "searching", "expanding", "generating", "verifying"]
    assert events[0]["data"]["label"] == "Understanding your question"

    deltas = [e["data"]["text"] for e in events if e["event"] == "delta"]
    assert deltas and deltas[-1].startswith("보증금")
    assert any(e["event"] == "reset" for e in events)  # 인용 실패로 재생성할 때 앱이 화면을 비운다
    answer = events[-1]["data"]
    assert answer["lang"] == "en"
    assert fake_llm.count("LegalAnswer") == 2  # 인용 실패로 1회 재생성
    assert [c["verified"] for c in answer["citations"]] == [True, True]
    assert answer["confidence"] == "high"
    retrieved = {src["provision_id"] for src in answer["sources"]}
    assert "02/2024/NĐ-TEST:D2" in retrieved
    assert answer["disclaimer"].startswith("This is legal information")
    assert answer["number_checks"] == []  # 답변에 단위 붙은 숫자 없음 ("3개월치"는 한국어)
    assert answer["analysis_id"] is None
    assert answer["usage"]["calls"] == 0  # 가짜 LLM은 사용량을 남기지 않는다


def test_any_language_question_gets_english_messages(fake_llm):
    async def go():
        if not await _samples_loaded():
            pytest.skip("로컬 DB에 샘플 법령이 없음")
        async with SessionLocal() as s:
            return [ev async for ev in answer_stream(s, ChatRequest(message="Tiền đặt cọc tối đa là bao nhiêu?"))]

    events = _run(go())
    assert events[0]["data"]["label"] == "Understanding your question"
    assert events[-1]["data"]["lang"] == "en"
    assert events[-1]["data"]["disclaimer"].startswith("This is legal information")
