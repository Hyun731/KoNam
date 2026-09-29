"""검색·인용 품질 평가.

  python -m eval.run_eval eval/datasets/golden_qa.jsonl            # 검색만 (Recall@k, MRR)
  python -m eval.run_eval eval/datasets/golden_qa.jsonl --generate # 답변 생성 + 인용 정확도
  python -m eval.run_eval ... --no-graph                           # 그래프 확장 끄고 비교

데이터셋 한 줄 형식:
{"id": "q1", "question": "...", "expected": ["91/2015/QH13:D418"], "as_of": null}
expected는 조(Điều) 또는 그 하위 ID. 조 단위로 맞았는지 본다.
"""

import argparse
import asyncio
import json
import time
from datetime import date
from pathlib import Path

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.retrieval.pipeline import retrieve
from app.retrieval.rewrite import resolve_as_of, rewrite_query


def dieu_of(pid: str) -> str:
    parts = pid.split(":")
    for i, p in enumerate(parts):
        if p.startswith("D") and p[1:2].isdigit():
            return ":".join(parts[: i + 1])
    return pid


async def run(path: Path, k: int, generate: bool, no_graph: bool) -> None:
    settings = get_settings()
    if no_graph:
        settings.graph_hops = 0
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    recalls, rrs, cite_total, cite_ok, latencies = [], [], 0, 0, []
    details = []

    async with SessionLocal() as session:
        for row in rows:
            t0 = time.perf_counter()
            lang = "en"
            rq = await rewrite_query(row["question"], lang, [])
            as_of = resolve_as_of(rq, date.fromisoformat(row["as_of"]) if row.get("as_of") else None)
            items = await retrieve(
                session, rq.queries_vi, rq.standalone_question, as_of, list(rq.domains),
                include_samples=settings.include_samples,
            )
            latencies.append(time.perf_counter() - t0)

            expected = {dieu_of(e) for e in row["expected"]}
            got = [dieu_of(i.provision_id) for i in items[:k]]
            hit = expected & set(got)
            recalls.append(len(hit) / len(expected) if expected else 0.0)
            first = next((n for n, g in enumerate(got, 1) if g in expected), None)
            rrs.append(1 / first if first else 0.0)
            detail = {"id": row["id"], "recall": recalls[-1], "rank": first, "got": got[:5], "queries": rq.queries_vi}

            if generate and items:
                from app.generation.answer import generate_answer
                from app.generation.verify import check_citation, lookup

                ans = await generate_answer(rq.standalone_question, items, lang, as_of, [])
                infos = await lookup(session, [c.provision_id for c in ans.citations], as_of)
                checks = [check_citation(c.provision_id, c.quote_vi, infos.get(c.provision_id)) for c in ans.citations]
                cite_total += len(checks)
                cite_ok += sum(c.ok for c in checks)
                detail["citation_errors"] = [f"{c.provision_id}: {c.reason}" for c in checks if not c.ok]
            details.append(detail)
            print(f"{row['id']:>8}  recall={recalls[-1]:.2f}  rank={first}  {rq.queries_vi[:1]}")

    n = len(rows) or 1
    print("\n=== 결과 ===")
    print(f"질문 수          {len(rows)}")
    print(f"Recall@{k:<9} {sum(recalls) / n:.3f}")
    print(f"MRR              {sum(rrs) / n:.3f}")
    lat = sorted(latencies)
    if lat:
        print(f"검색 지연 p95    {lat[int(len(lat) * 0.95) - 1 if len(lat) > 1 else 0]:.2f}s")
    if generate:
        print(f"인용 정확도      {cite_ok / cite_total if cite_total else 0:.3f} ({cite_ok}/{cite_total})")

    out = path.with_suffix(f".result.{int(time.time())}.json")
    out.write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"상세 결과: {out}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("dataset")
    p.add_argument("-k", type=int, default=10)
    p.add_argument("--generate", action="store_true")
    p.add_argument("--no-graph", action="store_true")
    a = p.parse_args()
    asyncio.run(run(Path(a.dataset), a.k, a.generate, a.no_graph))


if __name__ == "__main__":
    main()
