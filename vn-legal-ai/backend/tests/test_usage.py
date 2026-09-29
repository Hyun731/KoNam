import asyncio
from types import SimpleNamespace

from app import llm
from app.services.qa import build_analysis_context


def _resp_usage(inp, out, reasoning=0):
    return SimpleNamespace(input_tokens=inp, output_tokens=out,
                           output_tokens_details=SimpleNamespace(reasoning_tokens=reasoning))


def test_usage_accumulates_cost_by_model_prefix():
    with llm.track_usage() as u:
        llm._record("gpt-5", _resp_usage(1_000_000, 100_000, 50_000))
        llm._record("gpt-5-mini-2025-08-07", _resp_usage(2_000_000, 0))
        llm._record("text-embedding-3-large", SimpleNamespace(prompt_tokens=1_000_000, total_tokens=1_000_000))
    assert u.calls == 3
    assert u.input_tokens == 4_000_000
    assert u.output_tokens == 100_000
    assert u.reasoning_tokens == 50_000
    # gpt-5: 1.25 + 0.1*10 = 2.25, mini: 2*0.25 = 0.5, embedding: 0.13
    assert abs(u.cost_usd - 2.88) < 1e-9
    assert set(u.by_model) == {"gpt-5", "gpt-5-mini-2025-08-07", "text-embedding-3-large"}
    assert u.as_dict()["cost_usd"] == 2.88


def test_no_tracking_outside_block_and_nested_blocks_propagate():
    llm._record("gpt-5", _resp_usage(10, 10))  # 활성 누계기 없음 → 무시
    with llm.track_usage() as outer:
        with llm.track_usage() as inner:
            llm._record("gpt-5", _resp_usage(10, 20))
        llm._record("gpt-5", _resp_usage(1, 2))
    assert inner.calls == 1 and inner.output_tokens == 20
    assert outer.calls == 2 and outer.output_tokens == 22


def test_usage_is_shared_with_tasks_created_inside_block():
    async def call():
        await asyncio.sleep(0)
        llm._record("gpt-5", _resp_usage(5, 5))

    async def go():
        with llm.track_usage() as u:
            await asyncio.gather(call(), asyncio.create_task(call()))
        return u

    assert asyncio.run(go()).calls == 2


def test_analysis_context_reads_optional_fields_defensively():
    intake = {"title": "Biên bản vi phạm", "doc_type_label": "Violation record", "summary": "Drunk driving ticket.",
              "questions": [{"id": "q1", "text": "Were you the driver?", "options": [{"id": "a", "label": "Yes"}]}],
              "search_queries_vi": ["nồng độ cồn xe máy"]}
    result = {
        "summary": "A record of a drunk-driving violation on a motorbike.",
        "as_of": "2025-03-01",
        "confirmed_facts": [{"label": "Vehicle", "value": "motorbike"}, "Breath alcohol 0.3 mg/l"],
        "clauses": [
            {"id": "C1", "title": "Header", "category": "general", "text": "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM"},
            {"id": "C2", "title": "Fine", "category": "must_check", "explanation": "You must pay within 10 days.",
             "text": "Phạt tiền 2.000.000 đồng " + "x" * 7000},
        ],
    }
    ctx = build_analysis_context("id-1", intake, [{"question_id": "q1", "option_id": "a"}], result)
    assert ctx.as_of.isoformat() == "2025-03-01"
    assert ctx.search_queries == ["nồng độ cồn xe máy"]
    assert "Vehicle: motorbike" in ctx.block and "Breath alcohol 0.3 mg/l" in ctx.block
    assert "Were you the driver? → Yes" in ctx.block
    assert "[C2] Fine (must_check)" in ctx.block  # 꼭 확인할 조항이 먼저 들어가고
    assert "[C1]" not in ctx.block  # 길이 한도를 다 쓰면 일반 조항은 뺀다
    assert len(ctx.block) < 7500  # 조항 원문은 약 6000자로 자른다
    assert ("document:C2", result["clauses"][1]["text"]) in ctx.sources
    # 새 필드가 없는 예전 결과·빈 값도 오류 없이 처리
    empty = build_analysis_context("id-2", None, None, None)
    assert empty.as_of is None and "Uploaded document" in empty.block
