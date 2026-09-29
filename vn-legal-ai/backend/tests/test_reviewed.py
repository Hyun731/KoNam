"""법령 검토 기록(#14) 테스트: 재적재해도 검토 기록이 유지되고 조문 API에 노출되는지.

임시 문서(ID: TEST/REVIEW-0003)를 적재했다가 지운다. DB 또는 0003 컬럼이 없으면 건너뛴다.
"""

import asyncio
import hashlib
from pathlib import Path

import pytest
from sqlalchemy import delete, text

from app.api.v1.provisions import get_provision
from app.core.db import SessionLocal, engine
from app.models.law import LegalDocument
from ingest import pipeline
from ingest.loader import RawDocument

DOC_ID = "TEST/REVIEW-0003"
BODY = "Điều 1. Phạm vi điều chỉnh\nNghị định này quy định thử nghiệm.\n"


def _raw(body: str) -> RawDocument:
    meta = {
        "id": DOC_ID, "doc_type": "nghi_dinh", "title_vi": "Nghị định thử nghiệm", "effective_from": "2025-01-01",
        "status": "con_hieu_luc", "is_sample": True,
    }
    return RawDocument(Path("."), meta, body, hashlib.sha256(body.encode()).hexdigest())


def _run(coro):
    async def wrapper():
        try:
            return await coro
        finally:
            await engine.dispose()

    return asyncio.run(wrapper())


async def _ready() -> bool:
    try:
        async with SessionLocal() as s:
            await s.execute(text("SELECT reviewed, reviewed_by, reviewed_at, review_note FROM legal_documents LIMIT 1"))
            return True
    except Exception:
        return False


def test_review_survives_reload_and_is_exposed():
    if not _run(_ready()):
        pytest.skip("DB 없음 또는 0003 마이그레이션 미적용")

    async def go():
        async with SessionLocal() as s:
            try:
                await pipeline.load_documents(s, [_raw(BODY)])
                d = await pipeline.set_review(s, DOC_ID, "tester", "원문 대조 완료")
                assert d.reviewed and d.reviewed_at is not None

                # 원문이 바뀌어 다시 적재돼도 검토 기록은 유지
                await pipeline.load_documents(s, [_raw(BODY + "Điều 2. Hiệu lực\nCó hiệu lực.\n")])
                s.expunge_all()
                d = await s.get(LegalDocument, DOC_ID)
                assert (d.reviewed, d.reviewed_by, d.review_note) == (True, "tester", "원문 대조 완료")

                out = await get_provision(id=f"{DOC_ID}:D2", session=s)
                assert out.reviewed and out.reviewed_by == "tester" and out.reviewed_at is not None

                d = await pipeline.set_review(s, DOC_ID, None, unset=True)
                assert not d.reviewed and d.reviewed_by is None
            finally:
                await s.rollback()
                await s.execute(delete(LegalDocument).where(LegalDocument.id == DOC_ID))
                await s.commit()

    _run(go())
