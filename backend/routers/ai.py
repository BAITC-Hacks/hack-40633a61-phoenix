"""POST /api/ai/ask — вопрос на естественном языке -> ответ AI-ассистента."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import ai_assistant
from ..config import get_settings
from ..data_store import Dataset
from ..deps import get_dataset
from ..schemas import AICitation, AIAskRequest, AIAskResponse

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/status")
def ai_status() -> dict:
    """Настроен ли AI-ассистент — фронтенд использует это, чтобы не спамить
    пользователя ошибками, а сразу показать корректное состояние в Investigation."""
    settings = get_settings()
    return {
        "configured": settings.ai_api_key is not None,
        "model": settings.ai_model,
        "base_url": settings.ai_api_base_url,
    }


@router.post("/ask", response_model=AIAskResponse)
async def ask(payload: AIAskRequest, ds: Dataset = Depends(get_dataset)) -> AIAskResponse:
    """Отвечает на вопрос аналитика. 503, если AI_API_KEY не настроен —
    остальной дашборд при этом продолжает работать без интернета/ключа."""
    try:
        result = await ai_assistant.ask(payload.question, ds)
    except ai_assistant.AIAssistantNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ai_assistant.AIAssistantUpstreamError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return AIAskResponse(
        answer=result.answer,
        citations=[AICitation(**c) for c in result.citations],
        model=result.model,
    )
