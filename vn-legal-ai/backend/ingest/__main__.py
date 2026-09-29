"""적재 CLI

  python -m ingest check data/laws                 # DB 없이 파싱·관계 추출 결과만 확인
  python -m ingest load data/laws [--samples]      # 문서·조문·청크 적재 + 관계 재구성
  python -m ingest embed                           # 임베딩이 없는 청크 임베딩
  python -m ingest summarize --lang en             # 조별 영어 요약 청크 생성 (+ 이후 embed)
  python -m ingest all data/laws [--samples]       # load → summarize → embed
  python -m ingest fetch <URL> data/laws/<폴더명>   # 웹 페이지에서 본문 추출
  python -m ingest vbpl-fetch data/seeds/traffic.json  # VBPL SOAP에서 시드 목록 수집
  python -m ingest hf-export                       # HF 데이터셋에서 교통 법령 코퍼스 추출
  python -m ingest review <문서ID> --by 이름 [--note 메모] [--unset]  # 사람 검토 기록
  python -m ingest review --list                   # 검토/미검토 현황
"""

import argparse
import asyncio
import logging
from collections import Counter
from pathlib import Path

from ingest.loader import discover


def cmd_check(args) -> None:
    from ingest.parsers.structure import parse_law
    from ingest.pipeline import source_provisions
    from ingest.relations.resolver import DocMeta, resolve_edges

    docs = discover(Path(args.root), include_samples=args.samples)
    metas, provisions = [], []
    for raw in docs:
        parsed = parse_law(raw.text, raw.id, raw.meta["title_vi"])
        levels = Counter(n.level for n in parsed.nodes())
        print(f"■ {raw.id}  {raw.meta['title_vi']}")
        print(f"  조 {levels['dieu']} · 항 {levels['khoan']} · 호 {levels['diem']} · 장 {levels['chuong']}")
        for w in parsed.warnings:
            print(f"  ⚠ {w}")
        m = raw.meta
        metas.append(
            DocMeta(raw.id, m["title_vi"], tuple(m.get("short_names", [])), tuple(m.get("guides", [])),
                    tuple(m.get("amends", [])))
        )
        from types import SimpleNamespace

        rows = [SimpleNamespace(id=n.id, document_id=raw.id, dieu_id=(n.dieu().id if n.dieu() else None),
                                parent_id=n.parent.id if n.parent else None, level=n.level, heading=n.heading,
                                text_vi=n.text) for n in parsed.nodes()]
        provisions.extend(source_provisions(rows))

    edges, unresolved = resolve_edges(provisions, metas, {p.id for p in provisions})
    print(f"\n관계 {len(edges)}개: {dict(Counter(e.rel for e in edges))}")
    for e in edges[: args.show]:
        print(f"  {e.src_id} -[{e.rel}]-> {e.dst_id}   «{e.evidence}»")
    print(f"미해결 참조 {len(unresolved)}개")
    for u in unresolved[: args.show]:
        print(f"  {u.src_id}: {u.reason}   «{u.evidence}»")


async def _review(session, args) -> None:
    from ingest import pipeline

    if args.list or not args.doc_id:
        docs = await pipeline.list_reviews(session)
        done = [d for d in docs if d.reviewed]
        print(f"검토 완료 {len(done)} · 미검토 {len(docs) - len(done)} (샘플 제외 {len(docs)}건)")
        for d in docs:
            mark = "✔" if d.reviewed else "·"
            who = f"  {d.reviewed_by} {d.reviewed_at:%Y-%m-%d}" if d.reviewed and d.reviewed_at else ""
            note = f"  «{d.review_note}»" if d.review_note else ""
            print(f"  {mark} {d.id}  {d.title_vi[:60]}{who}{note}")
        return
    if not args.unset and not args.by:
        raise SystemExit("--by 이름을 지정하세요")
    try:
        d = await pipeline.set_review(session, args.doc_id, args.by, args.note, unset=args.unset)
    except LookupError as e:
        raise SystemExit(str(e)) from None
    state = f"검토 완료 ({d.reviewed_by}, {d.reviewed_at:%Y-%m-%d %H:%M})" if d.reviewed else "검토 해제"
    print(f"{d.id}: {state}")


async def _run(args) -> None:
    from app.core.db import SessionLocal
    from ingest import pipeline

    async with SessionLocal() as session:
        if args.cmd == "review":
            await _review(session, args)
            return
        if args.cmd in ("load", "all"):
            docs = discover(Path(args.root), include_samples=args.samples)
            await pipeline.load_documents(session, docs, force=args.force)
            await pipeline.rebuild_relations(session)
        if args.cmd == "relations":
            await pipeline.rebuild_relations(session)
        if args.cmd == "summarize" or (args.cmd == "all" and not args.no_summary):
            await pipeline.summarize_missing(session, lang=getattr(args, "lang", "en"))
        if args.cmd in ("embed", "all", "summarize"):
            await pipeline.embed_missing(session)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="python -m ingest")
    sub = p.add_subparsers(dest="cmd", required=True)

    for name in ("check", "load", "all"):
        s = sub.add_parser(name)
        s.add_argument("root", nargs="?", default="data/laws")
        s.add_argument("--samples", action="store_true", help="'_'로 시작하는 샘플 폴더도 포함")
        if name == "check":
            s.add_argument("--show", type=int, default=30)
        else:
            s.add_argument("--force", action="store_true", help="원문이 같아도 다시 적재")
        if name == "all":
            s.add_argument("--no-summary", action="store_true")
    sub.add_parser("relations")
    sub.add_parser("embed")
    s = sub.add_parser("summarize")
    s.add_argument("--lang", default="en", choices=["en", "ko"])
    s = sub.add_parser("hf-export")
    s.add_argument("--dataset-dir", default="data/hf")
    s.add_argument("--out", default="data/laws")
    s = sub.add_parser("vbpl-fetch")
    s.add_argument("seed")
    s.add_argument("--out", default="data/laws")
    s = sub.add_parser("review", help="법령 문서 사람 검토 기록")
    s.add_argument("doc_id", nargs="?")
    s.add_argument("--by", help="검토자 이름")
    s.add_argument("--note")
    s.add_argument("--unset", action="store_true", help="검토 기록 해제")
    s.add_argument("--list", action="store_true", help="검토 현황 목록")
    s = sub.add_parser("fetch")
    s.add_argument("url")
    s.add_argument("out")

    args = p.parse_args()
    if args.cmd == "check":
        cmd_check(args)
    elif args.cmd == "hf-export":
        from app.core.lang import today_vn
        from ingest.hf_dataset import export

        written = export(Path(args.dataset_dir), Path(args.out), today=today_vn())
        print(f"{len(written)}건 저장 → {args.out}")
    elif args.cmd == "vbpl-fetch":
        from ingest.crawlers.vbpl_soap import fetch_seed

        fetch_seed(Path(args.seed), Path(args.out))
    elif args.cmd == "fetch":
        from ingest.crawlers.fetch import fetch

        out = fetch(args.url, Path(args.out))
        print(f"저장: {out}/content.txt · metadata.json을 채운 뒤 `python -m ingest check`로 확인하세요")
    else:
        asyncio.run(_run(args))


if __name__ == "__main__":
    main()
