"""GraphRAG 컨텍스트 예산 테스트.

- _select: DB 없이 예산 배분 규칙 확인
- expand: 실제 DB의 개정 엣지(238/2026/NĐ-CP Điều 2 → 168/2024/NĐ-CP Điều 6)를 역방향으로 따라가는지 확인
- retrieve: 실제 검색(OpenAI 임베딩 1회)에서 개정 조문이 최종 컨텍스트에 들어가는지 확인
DB·데이터·API 키가 없으면 건너뛴다.
"""

import asyncio
from datetime import date

import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.retrieval.graph import GraphHit, expand
from app.retrieval.pipeline import ContextItem, _select, retrieve

AMENDED = "168/2024/NĐ-CP:D6"      # 자동차 운전자 위반 처벌 조
AMENDING = "238/2026/NĐ-CP:D2"     # "Sửa đổi, bổ sung một số điểm, khoản của Điều 6"
AS_OF = date(2026, 9, 29)


def _item(pid: str, score: float, source: str = "search") -> ContextItem:
    return ContextItem(pid, pid.split(":")[0], "t", None, "nghi_dinh", pid, "x", None, None, "con_hieu_luc",
                       score, source)


def _run(coro):
    async def wrapper():
        try:
            return await coro
        finally:
            await engine.dispose()

    return asyncio.run(wrapper())


async def _edge_exists() -> bool:
    try:
        async with SessionLocal() as s:
            n = (
                await s.execute(
                    text(
                        """SELECT count(*) FROM provision_edges e
                           JOIN provisions ps ON ps.id = e.src_id JOIN provisions pd ON pd.id = e.dst_id
                           WHERE e.rel = 'AMENDS' AND ps.dieu_id = :src AND pd.dieu_id = :dst"""
                    ),
                    {"src": AMENDING, "dst": AMENDED},
                )
            ).scalar_one()
            return n > 0
    except Exception:
        return False


# ── 예산 규칙 (DB 불필요) ───────────────────────────────────────────


def test_select_reserves_graph_slots_and_forces_amendment():
    search = [_item(f"A:D{i}", 1.0 - i * 0.01) for i in range(1, 16)]
    graph = [_item("B:D1", 0.05), _item("C:D1", 0.3), _item("C:D2", 0.2), _item("C:D3", 0.1)]
    hits = {
        "B:D1": GraphHit("B:D1", 0.05, "AMENDS ← A:D1", "AMENDS", "A:D1", 1, "reverse"),
        "C:D1": GraphHit("C:D1", 0.3, "REFERENCES → A:D2", "REFERENCES", "A:D2", 1, "forward"),
        "C:D2": GraphHit("C:D2", 0.2, "GUIDES ← A:D3", "GUIDES", "A:D3", 1, "reverse"),
        "C:D3": GraphHit("C:D3", 0.1, "REFERENCES → A:D4", "REFERENCES", "A:D4", 2, "forward"),
    }
    out = _select(search + graph, hits, {i.provision_id for i in search}, context_k=10, graph_slots=3)
    ids = [i.provision_id for i in out]
    assert len(out) == 10
    assert ids[:7] == [f"A:D{i}" for i in range(1, 8)]
    # 점수는 가장 낮아도 개정 조가 먼저, 그다음 GUIDES, REFERENCES
    assert ids[7:] == ["B:D1", "C:D2", "C:D1"]
    assert out[7].source == "graph: AMENDS ← A:D1"


def test_select_returns_unused_graph_slots_to_search():
    search = [_item(f"A:D{i}", 1.0 - i * 0.01) for i in range(1, 16)]
    hits = {"C:D1": GraphHit("C:D1", 0.3, "REFERENCES → A:D2", "REFERENCES", "A:D2")}
    out = _select(search + [_item("C:D1", 0.3)], hits, {i.provision_id for i in search}, 10, 3)
    assert len(out) == 10
    assert [i.provision_id for i in out].count("C:D1") == 1
    assert sum(i.source == "search" for i in out) == 9


def test_select_promotes_cut_seed_that_amends_selected_article():
    # 개정 조가 검색에도 걸렸지만 점수가 낮아 잘릴 위치일 때 → 그래프 예산으로 들어온다
    search = [_item(f"A:D{i}", 1.0 - i * 0.01) for i in range(1, 15)] + [_item("B:D1", 0.01)]
    hits = {"B:D1": GraphHit("B:D1", 0.8, "AMENDS ← A:D1", "AMENDS", "A:D1", 1, "reverse")}
    out = _select(search, hits, {i.provision_id for i in search}, 10, 3)
    b = next(i for i in out if i.provision_id == "B:D1")
    assert b.source == "graph: AMENDS ← A:D1"


# ── 실제 DB ─────────────────────────────────────────────────────────


def test_expand_follows_amends_in_reverse():
    if not _run(_edge_exists()):
        pytest.skip("DB 또는 238/2026 → 168/2024 개정 엣지 없음")

    async def go():
        async with SessionLocal() as s:
            return await expand(s, {AMENDED: 1.0}, AS_OF, hops=1, frontier_size=20)

    hits = _run(go())
    assert AMENDING in hits
    h = hits[AMENDING]
    assert (h.rel, h.direction, h.origin) == ("AMENDS", "reverse", AMENDED)
    assert h.via == f"AMENDS ← {AMENDED}"
    # 개정 조 시행 전 시점에는 나오지 않아야 한다
    before = _run(_expand_at(date(2026, 1, 1)))
    assert AMENDING not in before


async def _expand_at(as_of: date):
    async with SessionLocal() as s:
        return await expand(s, {AMENDED: 1.0}, as_of, hops=1, frontier_size=20)


def test_retrieve_includes_amendment_of_retrieved_article():
    if not _run(_edge_exists()):
        pytest.skip("DB 또는 238/2026 → 168/2024 개정 엣지 없음")
    if not get_settings().openai_api_key:
        pytest.skip("OpenAI 키 없음 (임베딩 필요)")

    q = "phạt tiền người điều khiển xe ô tô vượt đèn đỏ"

    async def go():
        async with SessionLocal() as s:
            return await retrieve(s, [q], q, AS_OF, None)

    items = _run(go())
    ids = [i.provision_id for i in items]
    assert AMENDED in ids, ids
    amend = next(i for i in items if i.provision_id == AMENDING)
    assert amend.source in ("search", f"graph: AMENDS ← {AMENDED}")
    assert len(items) <= get_settings().context_k
