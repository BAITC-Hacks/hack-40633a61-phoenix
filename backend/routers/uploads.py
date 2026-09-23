"""Multipart parquet upload and isolated pipeline runs."""

from __future__ import annotations

import json

from fastapi import APIRouter, File, HTTPException, UploadFile

from ..config import get_settings
from ..upload_service import UploadValidationError, create_analysis

router = APIRouter(prefix="/analyses", tags=["analyses"])


@router.post("", status_code=201)
async def upload_analysis(files: list[UploadFile] = File(...)) -> dict:
    """Validate parquet files, infer their logical schemas and run analysis."""
    try:
        return await create_analysis(files, get_settings().runs_dir)
    except UploadValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{analysis_id}")
def analysis_status(analysis_id: str) -> dict:
    if not analysis_id.isalnum() or len(analysis_id) != 32:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    metadata = get_settings().runs_dir / analysis_id / "analysis.json"
    if not metadata.exists():
        raise HTTPException(status_code=404, detail="Analysis not found.")
    return json.loads(metadata.read_text(encoding="utf-8"))
