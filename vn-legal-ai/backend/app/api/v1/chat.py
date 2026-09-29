import json
import logging
from contextlib import aclosing

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.schemas.chat import AnswerPayload, ChatRequest
from app.services.qa import AnalysisContext, answer_stream, load_analysis_context

router = APIRouter(prefix="/chat", tags=["chat"])
log = logging.getLogger(__name__)


async def _analysis(session: AsyncSession, req: ChatRequest) -> AnalysisContext | None:
    """문서 후속 질문이면 분석을 먼저 불러온다. 없는 ID는 스트림 시작 전에 404로 알린다."""
    if not req.analysis_id:
        return None
    ctx = await load_analysis_context(session, req.analysis_id)
    if ctx is None:
        raise HTTPException(404, "analysis_not_found")
    return ctx


@router.post("", response_model=AnswerPayload)
async def chat(req: ChatRequest, session: AsyncSession = Depends(get_session)):
    """단계 이벤트 없이 최종 답변만 JSON으로 돌려준다."""
    analysis = await _analysis(session, req)
    # 중간에 return 해도 제너레이터가 같은 컨텍스트에서 닫히도록 aclosing을 쓴다 (사용량 contextvar 정리)
    async with aclosing(answer_stream(session, req, analysis)) as events:
        async for ev in events:
            if ev["event"] == "answer":
                return ev["data"]
    raise RuntimeError("answer 이벤트가 생성되지 않았습니다")


@router.post("/stream")
async def chat_stream(req: ChatRequest, session: AsyncSession = Depends(get_session)):
    """SSE: event: stage (진행 단계) … delta … (reset) … event: answer (최종 답변) / event: error"""
    analysis = await _analysis(session, req)

    async def gen():
        try:
            async with aclosing(answer_stream(session, req, analysis)) as events:
                async for ev in events:
                    yield f"event: {ev['event']}\ndata: {json.dumps(ev['data'], ensure_ascii=False)}\n\n"
        except Exception:
            log.exception("chat stream 실패")
            yield 'event: error\ndata: {"message": "internal_error"}\n\n'

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
