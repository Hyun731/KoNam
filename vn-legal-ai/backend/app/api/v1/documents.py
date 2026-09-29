"""업로드 문서 기반 상담 API.

POST   /v1/documents               파일 업로드(또는 text 붙여넣기) → 텍스트 추출 + 사실·개인화 질문 생성 (status=questions)
PATCH  /v1/documents/{id}/facts    문서 사실 확인·수정 (status=questions일 때만)
POST   /v1/documents/{id}/answers  질문 답변 제출 → 백그라운드 분석 시작 (status=analyzing)
GET    /v1/documents/{id}          상태·단계·결과 조회 (앱이 폴링)
GET    /v1/documents               최근 분석 목록
DELETE /v1/documents/{id}          분석과 원문 텍스트 삭제
"""

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.lang import Lang
from app.documents.extract import UnsupportedDocument
from app.services import documents as svc

router = APIRouter(prefix="/documents", tags=["documents"])

DEMO_DIR = Path(__file__).resolve().parents[3] / "data" / "demo"
# 시연용 가상 문서 (실제 문서 아님)
SAMPLES = {
    "fine-red-light": {
        "file": "mau-quyet-dinh-xu-phat-vuot-den-do.docx",
        "title": {"en": "Sample · Red-light fine decision (motorbike)"},
    },
    "motorbike-rental": {
        "file": "mau-hop-dong-thue-xe-may.docx",
        "title": {"en": "Sample · Motorbike rental contract"},
    },
}
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class Answer(BaseModel):
    question_id: str
    option_id: str | None = None
    text: str | None = None


class AnswersIn(BaseModel):
    answers: list[Answer]


class FactIn(BaseModel):
    id: str | None = None  # GET 응답의 facts[].id (없으면 key+label로 찾는다)
    key: str
    label: str = ""
    value: str


class FactsIn(BaseModel):
    facts: list[FactIn]


@router.post("")
async def upload(
    file: UploadFile | None = File(None),
    text: str | None = Form(None),
    title: str | None = Form(None),
    lang: Lang = Form("en"),
    session: AsyncSession = Depends(get_session),
):
    """file 또는 text(붙여넣기, 30자 이상) 중 하나를 받는다."""
    try:
        if file is not None and (text or "").strip():
            raise svc.AnalysisError("Send either a file or pasted text, not both.")
        if file is not None:
            data = await file.read()
            return await svc.create_analysis(session, file.filename or "document", file.content_type, data, lang)
        if text is None:
            raise svc.AnalysisError("Upload a file or paste the document text.")
        filename, mime, data = svc.pasted_document(text, title)
        return await svc.create_analysis(session, filename, mime, data, lang)
    except (UnsupportedDocument, svc.AnalysisError) as e:
        raise HTTPException(422, str(e)) from e


@router.get("/samples")
async def samples():
    return [{"id": k, "title": v["title"], "filename": v["file"]} for k, v in SAMPLES.items()]


@router.post("/samples/{sample_id}")
async def analyze_sample(sample_id: str, lang: Lang = Form("en"), session: AsyncSession = Depends(get_session)):
    sample = SAMPLES.get(sample_id)
    if sample is None:
        raise HTTPException(404, "Sample not found.")
    data = (DEMO_DIR / sample["file"]).read_bytes()
    try:
        return await svc.create_analysis(session, sample["file"], DOCX_MIME, data, lang)
    except svc.AnalysisError as e:
        raise HTTPException(422, str(e)) from e


@router.get("")
async def recent(session: AsyncSession = Depends(get_session)):
    return await svc.list_analyses(session)


@router.get("/{analysis_id}")
async def get(analysis_id: str, session: AsyncSession = Depends(get_session)):
    view = await svc.get_analysis(session, analysis_id)
    if view is None:
        raise HTTPException(404, "Analysis not found.")
    return view


@router.patch("/{analysis_id}/facts")
async def facts(analysis_id: str, body: FactsIn, session: AsyncSession = Depends(get_session)):
    try:
        return await svc.update_facts(session, analysis_id, [f.model_dump() for f in body.facts])
    except svc.AnalysisNotFound as e:
        raise HTTPException(404, str(e)) from e
    except svc.AnalysisStateError as e:
        raise HTTPException(409, str(e)) from e
    except svc.AnalysisError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/{analysis_id}/answers")
async def answers(analysis_id: str, body: AnswersIn, session: AsyncSession = Depends(get_session)):
    try:
        return await svc.submit_answers(session, analysis_id, [a.model_dump() for a in body.answers])
    except svc.AnalysisError as e:
        raise HTTPException(422, str(e)) from e


@router.delete("/{analysis_id}", status_code=204)
async def delete(analysis_id: str, session: AsyncSession = Depends(get_session)):
    if not await svc.delete_analysis(session, analysis_id):
        raise HTTPException(404, "Analysis not found.")
