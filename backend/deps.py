"""Общие FastAPI-зависимости роутеров."""

from __future__ import annotations

from fastapi import HTTPException, Query

from .data_store import Dataset, OutputsNotReadyError, get_store


def get_dataset(
    analysis_id: str = Query(..., min_length=32, max_length=32),
) -> Dataset:
    """FastAPI dependency: актуальный :class:`Dataset` или понятная 503-ошибка."""
    try:
        return get_store().get(analysis_id)
    except OutputsNotReadyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
