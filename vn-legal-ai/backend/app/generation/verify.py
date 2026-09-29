"""인용 검증: 모델이 인용한 조문이 실제로 있고, 유효하고, 인용문이 원문에 있는지 코드로 확인한다."""

import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ingest.nlp.normalize import fold

_ELLIPSIS = re.compile(r"\.\.\.|…")
_POINT = re.compile(r":(?:P|điểm\s*|diem\s*)?([a-zđ])$", re.I)
_CLAUSE = re.compile(r":(?:K|khoản\s*|khoan\s*)(\d+)", re.I)
_ARTICLE = re.compile(r":(?:D|Điều\s*|Dieu\s*)(\d+[a-z]?)(?=:|$)", re.I)


def normalize_provision_id(pid: str) -> str:
    """모델이 쓴 ID 변형을 표준형으로: '…:D7:K7:c' / '…:Điều 7:khoản 7:điểm c' → '…:D7:K7:Pc'"""
    pid = pid.strip().strip("[]")
    pid = _ARTICLE.sub(lambda m: f":D{m.group(1)}", pid)
    pid = _CLAUSE.sub(lambda m: f":K{m.group(1)}", pid)
    if re.search(r":K\d+:[^:]+$", pid):
        pid = _POINT.sub(lambda m: f":P{m.group(1).lower()}", pid)
    return pid


@dataclass
class ProvisionInfo:
    id: str
    full_text: str
    dieu_id: str | None
    dieu_full_text: str
    valid: bool


@dataclass
class CitationCheck:
    provision_id: str
    ok: bool
    reason: str | None = None
    corrected_id: str | None = None   # 인용문이 다른 항에 있으면 상위 조 ID로 교정


def quote_in_text(quote: str, source: str) -> bool:
    """생략부호(…)로 나뉜 조각이 모두 원문에 순서대로 있으면 통과."""
    src = fold(source)
    pos = 0
    parts = [fold(p) for p in _ELLIPSIS.split(quote)]
    parts = [p for p in parts if p]
    if not parts:
        return False
    for part in parts:
        idx = src.find(part, pos)
        if idx < 0:
            return False
        pos = idx + len(part)
    return True


def check_citation(provision_id: str, quote_vi: str, info: ProvisionInfo | None) -> CitationCheck:
    if info is None:
        return CitationCheck(provision_id, False, "존재하지 않는 조문 ID")
    if not info.valid:
        return CitationCheck(provision_id, False, "기준일에 효력이 없는 조문")
    if quote_in_text(quote_vi, info.full_text):
        return CitationCheck(provision_id, True, corrected_id=info.id if info.id != provision_id else None)
    if info.dieu_id and quote_in_text(quote_vi, info.dieu_full_text):
        return CitationCheck(provision_id, True, corrected_id=info.dieu_id)
    return CitationCheck(provision_id, False, "인용문이 조문 원문과 일치하지 않음")


LOOKUP_SQL = text(
    """
    SELECT p.id, p.full_text_vi, p.dieu_id,
           coalesce(dp.full_text_vi, p.full_text_vi) AS dieu_full_text,
           ((p.effective_from IS NULL OR p.effective_from <= :as_of)
             AND (p.effective_to IS NULL OR p.effective_to > :as_of)
             AND d.status <> 'het_hieu_luc') AS valid
    FROM provisions p
    JOIN legal_documents d ON d.id = p.document_id
    LEFT JOIN provisions dp ON dp.id = p.dieu_id
    WHERE p.id = ANY(:ids)
    """
)


async def lookup(session: AsyncSession, ids: list[str], as_of: date) -> dict[str, ProvisionInfo]:
    """원래 ID와 정규화한 ID 모두로 찾을 수 있게 돌려준다."""
    if not ids:
        return {}
    norm = {i: normalize_provision_id(i) for i in ids}
    rows = (await session.execute(LOOKUP_SQL, {"ids": list(set(norm.values())), "as_of": as_of})).all()
    found = {r.id: ProvisionInfo(r.id, r.full_text_vi, r.dieu_id, r.dieu_full_text, bool(r.valid)) for r in rows}
    return {i: found[n] for i, n in norm.items() if n in found}
