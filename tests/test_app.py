from __future__ import annotations

from dataclasses import replace
from io import BytesIO

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend import ai_assistant
from backend.app import app
from backend.config import get_settings
from backend.data_store import DataStore
from backend.upload_service import UploadValidationError, _column_map, _infer_kind


def parquet_bytes(frame: pd.DataFrame) -> bytes:
    target = BytesIO()
    frame.to_parquet(target, index=False)
    return target.getvalue()


def node_frame(ids: list[str] | None = None) -> pd.DataFrame:
    values = ids or ["A", "B", "C", "D"]
    return pd.DataFrame(
        {
            "id": values,
            "name": [f"Entity {value}" for value in values],
            "entity_type": ["account"] * len(values),
            "seed": [True] + [False] * (len(values) - 1),
        }
    )


def edge_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "from": ["A", "D"],
            "to": ["B", "C"],
            "value": [999_999, 2_000],
            "transaction_count": [99, 0],
        }
    )


def transaction_frame(unknown: bool = False) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "transaction_id": ["t1", "t2", "t3", "t4", "t5", "t6"],
            "sender": ["A", "A", "B", "C", "B", "D"],
            "receiver": ["B", "B", "C", "B", "D", "A" if not unknown else "UNKNOWN"],
            "amount": [10_000, 5_000, 9_500, 4_000, 8_000, 7_500],
            "timestamp": pd.to_datetime(
                ["2026-01-01", "2026-01-02", "2026-01-02", "2026-01-03", "2026-01-03", "2026-01-04"]
            ),
            "currency": ["KZT"] * 6,
            "channel": ["mobile", "web", "mobile", "branch", "web", "mobile"],
        }
    )


@pytest.fixture
def isolated_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    settings = replace(get_settings(), runs_dir=tmp_path / "runs")
    store = DataStore(settings.out_dir, settings.runs_dir)
    monkeypatch.setattr("backend.routers.uploads.get_settings", lambda: settings)
    monkeypatch.setattr("backend.routers.uploads.get_store", lambda: store)
    monkeypatch.setattr("backend.deps.get_store", lambda: store)
    return TestClient(app), settings


def upload(client: TestClient, *, unknown: bool = False):
    return client.post(
        "/api/analyses",
        files={
            "nodes": ("nodes.parquet", parquet_bytes(node_frame()), "application/octet-stream"),
            "edges": ("edges.parquet", parquet_bytes(edge_frame()), "application/octet-stream"),
            "transactions": (
                "transactions.parquet",
                parquet_bytes(transaction_frame(unknown=unknown)),
                "application/octet-stream",
            ),
        },
    )


def test_schema_inference_accepts_common_aliases() -> None:
    mapping = _column_map(["sender", "receiver", "amount", "timestamp", "transaction_id"])
    assert _infer_kind(mapping) == "transactions"
    assert mapping["src"] == "sender"
    assert mapping["dst"] == "receiver"
    assert mapping["tx_id"] == "transaction_id"


def test_schema_inference_rejects_unknown_schema() -> None:
    with pytest.raises(UploadValidationError, match="Schema not recognized"):
        _infer_kind(_column_map(["first_name", "comment"]))


def test_analytics_endpoints_require_active_analysis() -> None:
    client = TestClient(app)
    assert client.get("/api/summary").status_code == 422
    assert client.get("/api/graph").status_code == 422
    assert client.get("/api/ai/status").status_code == 422


def test_upload_requires_all_three_named_files(isolated_client) -> None:
    client, _settings = isolated_client
    response = client.post(
        "/api/analyses",
        files={"transactions": ("transactions.parquet", parquet_bytes(transaction_frame()), "application/octet-stream")},
    )
    assert response.status_code == 422
    missing = {item["loc"][-1] for item in response.json()["detail"]}
    assert missing == {"nodes", "edges"}


def test_unknown_ids_are_rejected_with_clear_report(isolated_client) -> None:
    client, _settings = isolated_client
    response = upload(client, unknown=True)
    assert response.status_code == 422
    assert "UNKNOWN" in response.json()["detail"]
    assert "nodes" in response.json()["detail"]


def test_three_file_analysis_preserves_real_transfers_and_risk(isolated_client) -> None:
    client, settings = isolated_client
    response = upload(client)
    assert response.status_code == 201, response.text
    body = response.json()
    analysis_id = body["analysis_id"]
    assert body["results"]["nodes"] == 4
    assert body["results"]["transactions"] == 6
    # 5 transaction pairs plus one edge-only structural pair (D -> C).
    assert body["results"]["edges"] == 6
    assert (settings.runs_dir / analysis_id / "out" / "transactions_enriched.parquet").exists()

    params = {"analysis_id": analysis_id, "view": "full"}
    graph = client.get("/api/graph", params=params)
    assert graph.status_code == 200, graph.text
    payload = graph.json()
    assert payload["aggregated"] is False
    by_pair = {(edge["source"], edge["target"]): edge for edge in payload["edges"]}
    # transactions are authoritative, not the conflicting uploaded edge amount.
    assert by_pair[("A", "B")]["sum_kzt"] == 15_000
    assert by_pair[("A", "B")]["n_tx"] == 2
    assert by_pair[("A", "B")]["tx_ids"] == ["t2", "t1"]
    assert by_pair[("B", "C")]["has_transactions"] is True
    assert by_pair[("D", "C")]["has_transactions"] is False
    assert 0 <= by_pair[("A", "B")]["risk_score"] <= 100

    node = client.get(f"/api/nodes/A?analysis_id={analysis_id}")
    assert node.status_code == 200, node.text
    detail = node.json()
    assert detail["attributes"]["name"] == "Entity A"
    assert detail["risk_explanation"].startswith("AML-гипотеза")
    assert {tx["tx_id"] for tx in detail["transactions"]} >= {"t1", "t2"}
    assert any(tx["details"]["currency"] == "KZT" for tx in detail["transactions"])

    clusters = client.get("/api/clusters", params={"analysis_id": analysis_id})
    assert clusters.status_code == 200
    assert all("risk_score" in cluster and "risk_explanation" in cluster for cluster in clusters.json())


def test_ai_no_key_is_scoped_and_non_fatal(isolated_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _settings = isolated_client
    analysis_id = upload(client).json()["analysis_id"]

    async def unavailable(*_args, **_kwargs):
        raise ai_assistant.AIAssistantNotConfiguredError("AI-ассистент не настроен")

    monkeypatch.setattr(ai_assistant, "ask", unavailable)
    response = client.post(
        f"/api/ai/ask?analysis_id={analysis_id}",
        json={"question": "Какие есть риски?", "language": "ru", "selected_gid": "A"},
    )
    assert response.status_code == 503
    assert "не настроен" in response.json()["detail"]
    assert client.get("/api/summary", params={"analysis_id": analysis_id}).status_code == 200


def test_delete_analysis_removes_active_run(isolated_client) -> None:
    client, settings = isolated_client
    analysis_id = upload(client).json()["analysis_id"]
    response = client.delete(f"/api/analyses/{analysis_id}")
    assert response.status_code == 204
    assert not (settings.runs_dir / analysis_id).exists()
    missing = client.get("/api/summary", params={"analysis_id": analysis_id})
    assert missing.status_code == 503
