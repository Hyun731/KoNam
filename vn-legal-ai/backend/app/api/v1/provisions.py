"""조문 조회. 문서번호에 '/'가 들어가므로 ID는 쿼리 파라미터로 받는다."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.schemas.provision import ProvisionOut, RelatedOut

router = APIRouter(prefix="/provisions", tags=["provisions"])

GET_SQL = text(
    """
    SELECT p.id, p.document_id, p.level, p.path, p.full_text_vi, p.effective_from, p.effective_to,
           d.title_vi, d.title_ko, d.status, d.source_url, d.reviewed, d.reviewed_by, d.reviewed_at,
           (SELECT c.content FROM chunks c
             WHERE c.dieu_id = coalesce(p.dieu_id, p.id) AND c.kind = 'summary' AND c.lang = 'en' LIMIT 1)
             AS summary_en
    FROM provisions p JOIN legal_documents d ON d.id = p.document_id
    WHERE p.id = :id
    """
)

RELATED_SQL = text(
    """
    SELECT e.dst_id AS other, e.rel, 'outgoing' AS direction, e.evidence
    FROM provision_edges e JOIN provisions p ON p.id = e.src_id
    WHERE p.id = :id OR p.dieu_id = :id
    UNION ALL
    SELECT e.src_id AS other, e.rel, 'incoming' AS direction, e.evidence
    FROM provision_edges e JOIN provisions p ON p.id = e.dst_id
    WHERE p.id = :id OR p.dieu_id = :id
    """
)


@router.get("", response_model=ProvisionOut)
async def get_provision(id: str = Query(..., examples=["91/2015/QH13:D418"]), session: AsyncSession = Depends(get_session)):
    r = (await session.execute(GET_SQL, {"id": id})).first()
    if r is None:
        raise HTTPException(404, "조문을 찾을 수 없습니다")
    return ProvisionOut(
        id=r.id,
        document_id=r.document_id,
        document_title_vi=r.title_vi,
        document_title_ko=r.title_ko,
        level=r.level,
        path=r.path,
        text_vi=r.full_text_vi,
        summary_en=r.summary_en,
        effective_from=r.effective_from,
        effective_to=r.effective_to,
        status=r.status,
        source_url=r.source_url,
        reviewed=r.reviewed,
        reviewed_by=r.reviewed_by,
        reviewed_at=r.reviewed_at,
    )


@router.get("/related", response_model=list[RelatedOut])
async def related(id: str = Query(...), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(RELATED_SQL, {"id": id})).all()
    others = list({r.other for r in rows})
    paths = dict(
        (await session.execute(text("SELECT id, path FROM provisions WHERE id = ANY(:ids)"), {"ids": others})).all()
    ) if others else {}
    return [
        RelatedOut(provision_id=r.other, path=paths.get(r.other, r.other), rel=r.rel, direction=r.direction,
                   evidence=r.evidence)
        for r in rows
    ]
