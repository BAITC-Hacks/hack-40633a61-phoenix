"""Multipart parquet upload and isolated pipeline runs."""

from __future__ import annotations

import json
import shutil

from fastapi import APIRouter, File, HTTPException, UploadFile

from ..config import get_settings
from ..data_store import get_store
from ..upload_service import UploadValidationError, create_analysis

router = APIRouter(prefix="/analyses", tags=["analyses"])


@router.post("", status_code=201)
async def upload_analysis(
    nodes: UploadFile = File(...),
    edges: UploadFile = File(...),
    transactions: UploadFile = File(...),
) -> dict:
    """Validate the mandatory three-file dataset and run an isolated analysis."""
    try:
        return await create_analysis(
            {"nodes": nodes, "edges": edges, "transactions": transactions},
            get_settings().runs_dir,
        )
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


@router.delete("/{analysis_id}", status_code=204)
def delete_analysis(analysis_id: str) -> None:
    if not analysis_id.isalnum() or len(analysis_id) != 32:
        raise HTTPException(status_code=404, detail="Анализ не найден.")
    run_dir = get_settings().runs_dir / analysis_id
    if not run_dir.is_dir():
        raise HTTPException(status_code=404, detail="Анализ не найден.")
    get_store().invalidate(analysis_id)
    shutil.rmtree(run_dir)
