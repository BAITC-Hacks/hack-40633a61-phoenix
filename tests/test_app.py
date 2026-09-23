from __future__ import annotations

from dataclasses import replace
from io import BytesIO

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend import ai_assistant
from backend.app import app
from backend.config import get_settings
from backend.upload_service import UploadValidationError, _column_map, _infer_kind


def parquet_bytes(frame: pd.DataFrame) -> bytes:
    target = BytesIO()
    frame.to_parquet(target, index=False)
    return target.getvalue()


def transaction_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "transaction_id": ["t1", "t2", "t3", "t4", "t5", "t6"],
            "source": ["A", "B", "C", "B", "D", "A"],
            "target": ["B", "C", "B", "D", "A", "D"],
            "amount": [10_000, 9_500, 4_000, 8_000, 7_500, 2_500],
            "timestamp": pd.to_datetime(
                ["2026-01-01", "2026-01-01", "2026-01-02", "2026-01-02", "2026-01-03", "2026-01-03"]
            ),
        }
    )


def test_schema_inference_accepts_universal_aliases() -> None:
    mapping = _column_map(["source", "target", "amount", "timestamp", "transaction_id"])
    assert _infer_kind(mapping) == "transactions"
    assert mapping == {
        "src": "source", "dst": "target", "sum_kzt": "amount",
        "date": "timestamp", "tx_id": "transaction_id",
    }


def test_schema_inference_rejects_unknown_schema() -> None:
    with pytest.raises(UploadValidationError, match="Schema not recognized"):
        _infer_kind(_column_map(["first_name", "comment"]))


def test_summary_and_nodes_api() -> None:
    client = TestClient(app)
    summary = client.get("/api/summary")
    assert summary.status_code == 200
    assert summary.json()["n_nodes"] > 0
    nodes = client.get("/api/nodes?page_size=2")
    assert nodes.status_code == 200
    assert len(nodes.json()["items"]) == 2


def test_ai_endpoint_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    async def unavailable(*_args, **_kwargs):
        raise ai_assistant.AIAssistantNotConfiguredError("AI-ассистент не настроен")

    monkeypatch.setattr(ai_assistant, "ask", unavailable)
    response = TestClient(app).post("/api/ai/ask", json={"question": "Какие есть риски?"})
    assert response.status_code == 503
    assert "не настроен" in response.json()["detail"]


def test_upload_endpoint_happy_path_and_pipeline_smoke(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = replace(get_settings(), runs_dir=tmp_path / "runs")
    monkeypatch.setattr("backend.routers.uploads.get_settings", lambda: settings)
    response = TestClient(app).post(
        "/api/analyses",
        files={"files": ("transactions.parquet", parquet_bytes(transaction_frame()), "application/octet-stream")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["results"] == {
        "nodes": 4,
        "edges": 6,
        "transactions": 6,
        "ids_remapped": True,
        "date_min": "2026-01-01T00:00:00",
        "date_max": "2026-01-03T00:00:00",
    }
    assert (settings.runs_dir / body["analysis_id"] / "out" / "graph_export.json").exists()


def test_upload_endpoint_rejects_non_parquet(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = replace(get_settings(), runs_dir=tmp_path / "runs")
    monkeypatch.setattr("backend.routers.uploads.get_settings", lambda: settings)
    response = TestClient(app).post(
        "/api/analyses",
        files={"files": ("notes.txt", b"not parquet", "text/plain")},
    )
    assert response.status_code == 422
    assert "only .parquet" in response.json()["detail"]
