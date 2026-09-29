from datetime import date, datetime

from pydantic import BaseModel


class ProvisionOut(BaseModel):
    id: str
    document_id: str
    document_title_vi: str
    document_title_ko: str | None
    level: str
    path: str
    text_vi: str
    summary_en: str | None
    effective_from: date | None
    effective_to: date | None
    status: str
    source_url: str | None
    # 법령 문서 단위 사람 검토 기록 (#14)
    reviewed: bool = False
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None


class RelatedOut(BaseModel):
    provision_id: str
    path: str
    rel: str
    direction: str       # outgoing: 이 조문이 가리킴 / incoming: 이 조문을 가리킴
    evidence: str | None
