"""업로드 문서 기반 상담: 업로드 → 개인화 질문(필수) → 분석(백그라운드) → 결과."""

import asyncio
import json
import logging
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.lang import Lang, t, today_vn
from app.documents import facts as fx
from app.documents.analyze import DocumentAnalysis, run_analysis
from app.documents.extract import extract_text
from app.documents.intake import Intake, Question, run_intake
from app.documents.segment import Segment, segment_document
from app.generation.answer import Citation
from app.generation.verify import check_citation, lookup, quote_in_text
from app.retrieval.pipeline import retrieve

log = logging.getLogger(__name__)
STAGES = ["extracted", "structure", "situation", "writing"]
_tasks: set[asyncio.Task] = set()


PASTE_MIN_CHARS = 30


class AnalysisError(Exception):
    pass


class AnalysisNotFound(AnalysisError):
    pass


class AnalysisStateError(AnalysisError):
    """현재 상태에서는 할 수 없는 요청 (409)."""


def pasted_document(text_in: str | None, title: str | None) -> tuple[str, str, bytes]:
    """붙여넣은 텍스트 → (파일명, mime, 바이트). 파일을 읽을 수 없을 때 쓰는 입력 경로."""
    body = (text_in or "").strip()
    if len(body) < PASTE_MIN_CHARS:
        raise AnalysisError(f"Please paste at least {PASTE_MIN_CHARS} characters of the document text.")
    name = " ".join((title or "").split())[:80] or "Pasted text"
    return f"{name}.txt", "text/plain", body.encode("utf-8")


def _doc_facts(intake: dict) -> list[dict]:
    """인테이크가 뽑은 원래 사실(문서의 주장) — id는 저장된 사실과 같다."""
    return fx.initial_facts(intake.get("facts") or [])


def _row_view(r) -> dict:
    intake = r.intake or {}
    result = r.result
    return {
        "id": str(r.id),
        "created_at": r.created_at.isoformat(),
        "lang": r.lang,
        "filename": r.filename,
        "file_size": r.file_size,
        "page_count": r.page_count,
        "status": r.status,
        "stage": r.stage,
        "error": r.error,
        "title": intake.get("title"),
        "doc_type_label": intake.get("doc_type_label"),
        "questions": intake.get("questions", []),
        "facts": fx.public(r.facts or []),
        "answers": r.answers,
        "result": result,
    }


async def get_analysis(session: AsyncSession, analysis_id: str) -> dict | None:
    r = (await session.execute(text("SELECT * FROM analyses WHERE id = :id"), {"id": analysis_id})).first()
    return _row_view(r) if r else None


async def list_analyses(session: AsyncSession, limit: int = 20) -> list[dict]:
    rows = (
        await session.execute(text("SELECT * FROM analyses ORDER BY created_at DESC LIMIT :n"), {"n": limit})
    ).all()
    out = []
    for r in rows:
        v = _row_view(r)
        counts = (v["result"] or {}).get("counts")
        out.append({k: v[k] for k in ("id", "created_at", "filename", "status", "title", "doc_type_label")}
                   | {"counts": counts})
    return out


async def delete_analysis(session: AsyncSession, analysis_id: str) -> bool:
    res = await session.execute(text("DELETE FROM analyses WHERE id = :id"), {"id": analysis_id})
    await session.commit()
    return res.rowcount > 0


async def create_analysis(session: AsyncSession, filename: str, mime: str | None, data: bytes, lang: Lang) -> dict:
    extracted = await extract_text(filename, mime, data)
    if len(extracted.text.strip()) < 30:
        raise AnalysisError("We couldn't read text from this document. Try a clearer file, or paste the text instead.")
    segments = segment_document(extracted.text)
    intake = await run_intake(segments, filename, lang)
    facts = fx.initial_facts([f.model_dump() for f in intake.facts])
    if not fx.has_incident_date(facts):  # 사건일을 모르면 효력 기준일을 정할 수 있게 질문을 붙인다
        intake.questions = [q for q in intake.questions if q.id != fx.DATE_QUESTION_ID]
        intake.questions.append(Question.model_validate(fx.date_question(lang)))

    analysis_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO analyses (id, lang, filename, mime, file_size, page_count, text, status, stage, intake, facts)
            VALUES (:id, :lang, :filename, :mime, :size, :pages, :text, 'questions', 'extracted',
                    CAST(:intake AS jsonb), CAST(:facts AS jsonb))
            """
        ),
        {
            "id": analysis_id,
            "lang": lang,
            "filename": filename,
            "mime": mime,
            "size": len(data),
            "pages": extracted.page_count,
            "text": extracted.text,
            "intake": intake.model_dump_json(),
            "facts": json.dumps(facts, ensure_ascii=False),
        },
    )
    await session.commit()
    return await get_analysis(session, str(analysis_id))


async def update_facts(session: AsyncSession, analysis_id: str, submitted: list[dict]) -> dict:
    """사용자가 문서 사실을 확인·수정한다 (질문 단계에서만)."""
    r = (await session.execute(text("SELECT * FROM analyses WHERE id = :id FOR UPDATE"), {"id": analysis_id})).first()
    if r is None:
        raise AnalysisNotFound("Analysis not found.")
    if r.status != "questions":
        raise AnalysisStateError("Facts can only be changed before the analysis starts.")
    try:
        merged = fx.merge_facts(r.facts or [], submitted, _doc_facts(r.intake or {}))
    except fx.FactError as e:
        raise AnalysisError(str(e)) from e
    await session.execute(
        text("UPDATE analyses SET facts = CAST(:f AS jsonb), updated_at = now() WHERE id = :id"),
        {"id": analysis_id, "f": json.dumps(merged, ensure_ascii=False)},
    )
    await session.commit()
    return await get_analysis(session, analysis_id)


async def submit_answers(session: AsyncSession, analysis_id: str, answers: list[dict]) -> dict:
    r = (await session.execute(text("SELECT * FROM analyses WHERE id = :id"), {"id": analysis_id})).first()
    if r is None:
        raise AnalysisNotFound("Analysis not found.")
    facts = r.facts or []
    required = {q["id"] for q in (r.intake or {}).get("questions", [])}
    if any(f["key"] == "incident_date" and f["confirmed"] for f in facts):
        required.discard(fx.DATE_QUESTION_ID)  # 사건일을 이미 확인했으면 날짜 질문은 선택
    answered = {a["question_id"] for a in answers if a.get("option_id") or (a.get("text") or "").strip()}
    if not required <= answered:
        raise AnalysisError("Please answer all questions — the analysis is tailored to your answers.")
    facts = fx.apply_date_answer(facts, answers, today_vn())
    await session.execute(
        text(
            "UPDATE analyses SET answers = CAST(:a AS jsonb), facts = CAST(:f AS jsonb), status = 'analyzing', "
            "stage = 'extracted', error = NULL, updated_at = now() WHERE id = :id"
        ),
        {"id": analysis_id, "a": json.dumps(answers, ensure_ascii=False),
         "f": json.dumps(facts, ensure_ascii=False)},
    )
    await session.commit()
    task = asyncio.create_task(_run(analysis_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return await get_analysis(session, analysis_id)


async def _set(session: AsyncSession, analysis_id: str, **fields) -> None:
    sets = ", ".join(f"{k} = :{k}" if k != "result" else "result = CAST(:result AS jsonb)" for k in fields)
    await session.execute(text(f"UPDATE analyses SET {sets}, updated_at = now() WHERE id = :id"),
                          {"id": analysis_id, **fields})
    await session.commit()


async def _run(analysis_id: str) -> None:
    async with SessionLocal() as session:
        try:
            await _analyze(session, analysis_id)
        except Exception:
            log.exception("문서 분석 실패 %s", analysis_id)
            await _set(session, analysis_id, status="error", error="Something went wrong during the analysis. Please try again.")


async def _analyze(session: AsyncSession, analysis_id: str) -> None:
    r = (await session.execute(text("SELECT * FROM analyses WHERE id = :id"), {"id": analysis_id})).first()
    lang: Lang = r.lang
    intake = Intake.model_validate({"facts": [], **(r.intake or {})})  # facts 이전 행 호환
    answers = r.answers or []
    facts = r.facts or []
    # 효력 기준일 = 사건일 (확인된 사실 → 문서 → 오늘)
    as_of, as_of_source = fx.choose_as_of(facts, today_vn())
    claims = [{k: f[k] for k in ("key", "label", "value")} for f in _doc_facts(r.intake or {})]
    confirmed = [{k: f[k] for k in ("key", "label", "value", "source")} for f in facts if f["confirmed"]]

    await _set(session, analysis_id, stage="structure")
    segments = segment_document(r.text)

    await _set(session, analysis_id, stage="situation")
    queries = intake.search_queries_vi or [intake.summary]
    # 사용자가 고친 사실(위반 행위·차종 등)은 검색 원문에도 넣는다
    corrected = "; ".join(f"{f['label']}: {f['value']}" for f in confirmed if f["source"] == "user")
    original = f"{intake.doc_type_label}. {intake.summary}" + (f" Confirmed by user: {corrected}" if corrected else "")
    law = await retrieve(
        session, queries, original, as_of, ["giao_thong"],
        include_samples=get_settings().include_samples,
    )
    analysis = await run_analysis(segments, intake, answers, law, lang, as_of,
                                  document_claims=claims, confirmed_facts=confirmed)

    await _set(session, analysis_id, stage="writing")
    # 검증에 실패한 인용은 _build_result에서 빼고 보여준다. 전체 재생성은 분석 시간을 두 배로 늘리고,
    # 피드백에 답하는 메타 문장이 결과에 섞이는 문제가 있어 하지 않는다.
    failures = await _citation_failures(session, analysis, as_of)
    if failures:
        log.info("문서 분석 인용 %d건 검증 실패 → 제외", len(failures))

    result = await _build_result(session, intake, analysis, segments, law, lang, as_of)
    result |= {"as_of_source": as_of_source, "document_claims": claims, "confirmed_facts": confirmed,
               "page_count": r.page_count}
    await _set(session, analysis_id, status="done", stage="done", result=json.dumps(result, ensure_ascii=False))


def _all_citations(a: DocumentAnalysis) -> list[Citation]:
    return [c for x in a.clauses for c in x.citations] + [c for x in a.cautions for c in x.citations]


async def _citation_failures(session: AsyncSession, a: DocumentAnalysis, as_of) -> list[str]:
    cits = _all_citations(a)
    infos = await lookup(session, [c.provision_id for c in cits], as_of)
    out = []
    for c in cits:
        chk = check_citation(c.provision_id, c.quote_vi, infos.get(c.provision_id))
        if not chk.ok:
            out.append(f"- {c.provision_id}: {chk.reason}")
    return out


async def _build_result(session, intake: Intake, a: DocumentAnalysis, segments: list[Segment], law, lang: Lang, as_of):
    cits = _all_citations(a)
    infos = await lookup(session, [c.provision_id for c in cits], as_of)
    paths = dict(
        (await session.execute(
            text("SELECT id, path FROM provisions WHERE id = ANY(:ids)"),
            {"ids": list({c.provision_id for c in cits} | {(infos[c.provision_id].dieu_id or "") for c in cits
                                                           if c.provision_id in infos})},
        )).all()
    ) if cits else {}

    def cite(c: Citation) -> dict | None:
        chk = check_citation(c.provision_id, c.quote_vi, infos.get(c.provision_id))
        if not chk.ok:
            return None  # 재생성 후에도 검증에 실패한 인용은 보여주지 않는다
        pid = chk.corrected_id or c.provision_id
        return {"provision_id": pid, "path": paths.get(pid, pid), "quote_vi": c.quote_vi,
                "quote_translation": c.quote_translation}

    seg_by_id = {s.id: s for s in segments}
    seen: set[str] = set()
    clauses = []
    for f in a.clauses:
        seg = seg_by_id.get(f.clause_id)
        if not seg or f.clause_id in seen:
            continue
        seen.add(f.clause_id)
        clauses.append({
            "id": f.clause_id,
            "title": f.title,
            "category": f.category,
            "explanation": f.explanation_detail,
            "explanation_simple": f.explanation_simple,
            "explanation_detail": f.explanation_detail,
            "highlights": [h for h in f.highlights if h.strip() and quote_in_text(h, seg.text)],
            "text": seg.text,
            "pages": seg.pages,
            "citations": [x for x in map(cite, f.citations) if x],
        })
    for seg in segments:  # 모델이 언급하지 않은 조항은 일반 조항으로 둔다
        if seg.id not in seen:
            clauses.append({"id": seg.id, "title": seg.title, "category": "general", "explanation": None,
                            "explanation_simple": None, "explanation_detail": None,
                            "highlights": [], "text": seg.text, "pages": seg.pages, "citations": []})
    order = {s.id: i for i, s in enumerate(segments)}
    clauses.sort(key=lambda c: order.get(c["id"], 0))

    counts = {k: sum(c["category"] == k for c in clauses) for k in ("must_check", "caution", "general")}
    # 꼭 확인할 조항 대부분에 검증된 근거가 없으면 신뢰도를 낮춘다
    must = [c for c in clauses if c["category"] == "must_check"]
    uncited = sum(not c["citations"] for c in must)
    confidence = "low" if must and uncited * 2 > len(must) else a.confidence
    return {
        "title": intake.title,
        "doc_type_label": intake.doc_type_label,
        "doc_kind": intake.doc_kind,
        "summary": a.summary,
        "summary_simple": a.summary_simple,
        "situation_note": a.situation_note,
        "basic_info": [i.model_dump() for i in intake.basic_info],
        "counts": counts,
        "clauses": clauses,
        "cautions": [
            {"title": c.title, "detail": c.explanation_detail, "explanation": c.explanation_detail,
             "explanation_simple": c.explanation_simple, "explanation_detail": c.explanation_detail, "kind": c.kind,
             "clause_ids": [x for x in c.clause_ids if x in seg_by_id],
             "citations": [x for x in map(cite, c.citations) if x]}
            for c in a.cautions
        ],
        "next_actions": [
            {"id": f"a{i + 1}", "text": x.text, "clause_id": x.clause_id if x.clause_id in seg_by_id else None,
             "due": x.due}
            for i, x in enumerate(a.next_actions)
        ],
        "open_questions": [{"id": f"oq{i + 1}", "question": q.question, "why": q.why}
                           for i, q in enumerate(a.open_questions[:3])],
        "confidence": confidence,
        "needs_lawyer": a.needs_lawyer or confidence == "low",
        "notice": t("low_confidence", lang) if confidence == "low" else None,
        "not_traffic": intake.doc_kind == "not_traffic",
        "disclaimer": t("disclaimer", lang),
        "as_of": as_of.isoformat(),
        "law_sources": [{"provision_id": i.provision_id, "path": i.path} for i in law],
    }
