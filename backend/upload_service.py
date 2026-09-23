"""Safe parquet ingestion, schema inference and isolated analysis runs."""

from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq
from fastapi import UploadFile

from src.moneygraph.pipeline import run

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_ROWS = 500_000
REQUIRED_KINDS = ("nodes", "edges", "transactions")

ALIASES = {
    "src": ("src", "source", "from", "sender", "sender_id"),
    "dst": ("dst", "target", "to", "receiver", "receiver_id"),
    "sum_kzt": ("sum_kzt", "amount", "value"),
    "date": ("date", "timestamp"),
    "tx_id": ("tx_id", "transaction_id", "transaction id", "id"),
    "gid": ("gid", "node_id", "account_id", "entity_id", "id"),
    "is_seed": ("is_seed", "seed"),
    "depth": ("depth", "level", "hop"),
    "n_tx": ("n_tx", "transaction_count", "count"),
}


class UploadValidationError(ValueError):
    """User-facing validation error for an uploaded parquet."""


@dataclass
class IngestedFile:
    name: str
    path: Path
    columns: list[str]
    rows: int
    size: int
    kind: str
    mapping: dict[str, str]
    preview: list[dict[str, Any]]


def _safe_name(name: str | None, index: int) -> str:
    value = Path(name or f"upload-{index}.parquet").name
    if not value.lower().endswith(".parquet"):
        raise UploadValidationError(f"{value}: only .parquet files are accepted")
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)[:120]


def _column_map(columns: list[str]) -> dict[str, str]:
    by_lower = {str(c).strip().lower(): str(c) for c in columns}
    result: dict[str, str] = {}
    for canonical, aliases in ALIASES.items():
        matches = [by_lower[alias] for alias in aliases if alias in by_lower]
        if matches:
            # Alias order is deliberate: canonical names win over generic
            # alternatives such as ``id``.
            result[canonical] = matches[0]
    return result


def _infer_kind(mapping: dict[str, str]) -> str:
    keys = set(mapping)
    if {"src", "dst", "sum_kzt", "date"} <= keys:
        return "transactions"
    if {"src", "dst", "sum_kzt"} <= keys:
        return "edges"
    if "gid" in keys:
        return "nodes"
    raise UploadValidationError(
        "Schema not recognized. Expected nodes (gid), edges "
        "(src/source/from, dst/target/to, amount/sum_kzt/value), or transactions "
        "(the edge fields plus date/timestamp)."
    )


def _json_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return str(value) if not isinstance(value, (str, int, float, bool)) else value


async def save_and_inspect(
    files: dict[str, UploadFile],
    incoming_dir: Path,
) -> list[IngestedFile]:
    if set(files) != set(REQUIRED_KINDS):
        raise UploadValidationError(
            "Нужно загрузить ровно три файла: nodes, edges и transactions."
        )
    incoming_dir.mkdir(parents=True, exist_ok=False)
    results: list[IngestedFile] = []
    for index, expected_kind in enumerate(REQUIRED_KINDS):
        upload = files[expected_kind]
        name = _safe_name(upload.filename, index)
        path = incoming_dir / f"{index}-{name}"
        size = 0
        with path.open("wb") as target:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise UploadValidationError(
                        f"{name}: exceeds the {MAX_UPLOAD_BYTES // 1024 // 1024} MB per-file limit."
                    )
                target.write(chunk)
        if size < 4:
            raise UploadValidationError(f"{name}: empty or invalid parquet file.")
        try:
            metadata = pq.ParquetFile(path).metadata
            columns = list(pq.ParquetFile(path).schema_arrow.names)
        except Exception as exc:
            raise UploadValidationError(f"{name}: invalid parquet container ({exc}).") from exc
        rows = metadata.num_rows
        if rows <= 0 or rows > MAX_ROWS:
            raise UploadValidationError(f"{name}: row count must be 1..{MAX_ROWS:,}; got {rows:,}.")
        mapping = _column_map(columns)
        kind = _infer_kind(mapping)
        if kind != expected_kind:
            raise UploadValidationError(
                f"{name}: файл выбран как {expected_kind}, но его схема распознана как {kind}."
            )
        if kind == "nodes":
            mapping = {key: value for key, value in mapping.items() if key in {"gid", "is_seed", "depth"}}
        elif kind == "edges":
            mapping = {
                key: value
                for key, value in mapping.items()
                if key in {"src", "dst", "sum_kzt", "n_tx", "depth"}
            }
        else:
            mapping = {
                key: value
                for key, value in mapping.items()
                if key in {"src", "dst", "sum_kzt", "date", "tx_id"}
            }
        try:
            sample = pd.read_parquet(path, columns=columns).head(5)
        except Exception as exc:
            raise UploadValidationError(f"{name}: parquet data cannot be decoded ({exc}).") from exc
        preview = [{str(k): _json_value(v) for k, v in row.items()} for row in sample.to_dict("records")]
        results.append(IngestedFile(name, path, columns, rows, size, kind, mapping, preview))
    return results


def _read(item: IngestedFile) -> pd.DataFrame:
    try:
        return pd.read_parquet(item.path)
    except Exception as exc:
        raise UploadValidationError(f"{item.name}: failed to read parquet data ({exc}).") from exc


def _rename(df: pd.DataFrame, item: IngestedFile) -> pd.DataFrame:
    return df.rename(columns={actual: canonical for canonical, actual in item.mapping.items()})


def _normalize_amounts(df: pd.DataFrame, label: str) -> None:
    df["sum_kzt"] = pd.to_numeric(df["sum_kzt"], errors="coerce")
    if df["sum_kzt"].isna().any() or (df["sum_kzt"] < 0).any():
        raise UploadValidationError(f"{label}: amount/sum_kzt/value must contain finite non-negative numbers.")


def _normalize_identifier_column(df: pd.DataFrame, column: str, label: str) -> None:
    if df[column].isna().any():
        raise UploadValidationError(f"{label}: колонка {column} содержит пустые ID.")
    values = df[column].astype(str).str.strip()
    if values.eq("").any():
        raise UploadValidationError(f"{label}: колонка {column} содержит пустые ID.")
    df[column] = values


def _normalize_ids(frames: list[pd.DataFrame]) -> dict[str, int]:
    values: list[str] = []
    for frame in frames:
        for column in ("gid", "src", "dst"):
            if column in frame:
                values.extend(frame[column].astype(str).tolist())
    unique = sorted(set(values))
    numeric: dict[str, int] = {}
    try:
        numeric = {value: int(value) for value in unique}
        if len(set(numeric.values())) != len(unique) or any(v < 0 or v > 2**63 - 1 for v in numeric.values()):
            numeric = {}
    except ValueError:
        numeric = {}
    mapping = numeric or {value: index + 1 for index, value in enumerate(unique)}
    for frame in frames:
        for column in ("gid", "src", "dst"):
            if column in frame:
                frame[column] = frame[column].astype(str).map(mapping).astype("int64")
    return mapping


def prepare_dataset(items: list[IngestedFile], data_dir: Path) -> dict[str, Any]:
    by_kind = {item.kind: item for item in items}
    missing = set(REQUIRED_KINDS) - set(by_kind)
    if missing:
        raise UploadValidationError(
            "Отсутствуют обязательные файлы: " + ", ".join(sorted(missing)) + "."
        )
    tx = _rename(_read(by_kind["transactions"]), by_kind["transactions"])
    edges = _rename(_read(by_kind["edges"]), by_kind["edges"])
    nodes = _rename(_read(by_kind["nodes"]), by_kind["nodes"])

    for column in ("src", "dst"):
        _normalize_identifier_column(tx, column, "transactions")
        _normalize_identifier_column(edges, column, "edges")
    _normalize_identifier_column(nodes, "gid", "nodes")
    if nodes.gid.duplicated().any():
        duplicates = nodes.loc[nodes.gid.duplicated(keep=False), "gid"].unique()[:10]
        raise UploadValidationError(
            "nodes: ID должны быть уникальными. Дубликаты: "
            + ", ".join(map(str, duplicates))
            + "."
        )

    _normalize_amounts(tx, "transactions")
    tx["date"] = pd.to_datetime(tx["date"], errors="coerce", utc=True).dt.tz_localize(None)
    if tx["date"].isna().any():
        raise UploadValidationError("transactions: date/timestamp содержит некорректные даты.")
    if "tx_id" not in tx:
        tx["tx_id"] = [f"tx-{i + 1}" for i in range(len(tx))]
    _normalize_identifier_column(tx, "tx_id", "transactions")
    if tx.tx_id.duplicated().any():
        duplicates = tx.loc[tx.tx_id.duplicated(keep=False), "tx_id"].unique()[:10]
        raise UploadValidationError(
            "transactions: transaction ID должны быть уникальными. Дубликаты: "
            + ", ".join(map(str, duplicates))
            + "."
        )

    _normalize_amounts(edges, "edges")
    if "n_tx" not in edges:
        edges["n_tx"] = 0
    if "depth" not in edges:
        edges["depth"] = 1
    edges["n_tx"] = pd.to_numeric(edges["n_tx"], errors="coerce").fillna(0).clip(lower=0).astype(int)
    edges["depth"] = pd.to_numeric(edges["depth"], errors="coerce").fillna(1).astype(int)
    if "is_seed" not in nodes:
        nodes["is_seed"] = False
    nodes["is_seed"] = nodes["is_seed"].fillna(False).astype(bool)
    if "depth" not in nodes:
        nodes["depth"] = 0
    nodes["depth"] = pd.to_numeric(nodes["depth"], errors="coerce").fillna(0).astype(int)

    known = set(nodes.gid)
    references = set(tx.src) | set(tx.dst) | set(edges.src) | set(edges.dst)
    unknown = sorted(references - known)
    if unknown:
        sample = ", ".join(unknown[:20])
        suffix = f" (и ещё {len(unknown) - 20})" if len(unknown) > 20 else ""
        raise UploadValidationError(
            "edges/transactions ссылаются на ID, отсутствующие в nodes: "
            f"{sample}{suffix}. Добавьте их в nodes.parquet и повторите анализ."
        )

    frames = [tx, edges, nodes]
    id_mapping = _normalize_ids(frames)

    edge_agg = (
        edges.groupby(["src", "dst"], as_index=False)
        .agg(sum_kzt=("sum_kzt", "sum"), n_tx=("n_tx", "sum"), depth=("depth", "min"))
    )
    tx_agg = (
        tx.groupby(["src", "dst"], as_index=False)
        .agg(tx_sum_kzt=("sum_kzt", "sum"), tx_n_tx=("tx_id", "size"))
    )
    reconciled = edge_agg.merge(tx_agg, on=["src", "dst"], how="outer")
    reconciled["has_transactions"] = reconciled.tx_n_tx.notna()
    reconciled["sum_kzt"] = reconciled.tx_sum_kzt.fillna(reconciled.sum_kzt)
    reconciled["n_tx"] = reconciled.tx_n_tx.fillna(reconciled.n_tx).fillna(0).astype(int)
    reconciled["depth"] = reconciled.depth.fillna(1).astype(int)
    edges = reconciled[["src", "dst", "sum_kzt", "n_tx", "depth", "has_transactions"]]

    data_dir.mkdir(parents=True, exist_ok=False)
    nodes.to_parquet(data_dir / "nodes.parquet", index=False)
    edges.to_parquet(data_dir / "edges.parquet", index=False)
    tx.to_parquet(data_dir / "transactions.parquet", index=False)
    mapped = any(str(value) != str(mapped_value) for value, mapped_value in id_mapping.items())
    mapping_payload = {
        "external_to_internal": id_mapping,
        "internal_to_external": {str(value): key for key, value in id_mapping.items()},
    }
    (data_dir / "id_mapping.json").write_text(
        json.dumps(mapping_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "nodes": len(nodes),
        "edges": len(edges),
        "transactions": len(tx),
        "ids_remapped": mapped,
        "date_min": tx["date"].min().isoformat(),
        "date_max": tx["date"].max().isoformat(),
    }


async def create_analysis(files: dict[str, UploadFile], runs_dir: Path) -> dict[str, Any]:
    analysis_id = uuid.uuid4().hex
    run_dir = runs_dir / analysis_id
    try:
        items = await save_and_inspect(files, run_dir / "incoming")
        stats = prepare_dataset(items, run_dir / "data")
        try:
            run(run_dir / "data", run_dir / "out", build_viewer=False)
        except (AssertionError, ValueError) as exc:
            raise UploadValidationError(f"Dataset consistency validation failed: {exc}") from exc
        response = {
            "analysis_id": analysis_id,
            "status": "completed",
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "files": [
                {
                    "name": item.name, "kind": item.kind, "rows": item.rows,
                    "size": item.size, "columns": item.columns,
                    "column_mapping": item.mapping, "preview": item.preview,
                }
                for item in items
            ],
            "results": stats,
            "signals": [
                "consolidation", "fan-out", "pass-through", "cycles",
                "temporal bursts/structuring where timestamps and granularity allow",
            ],
            "confidence": "heuristic",
            "limitations": [
                "Risk signals are AML hypotheses for analyst review, not allegations.",
                "Unknown activity outside the uploaded period/network is not observable.",
                "Structuring below source-system thresholds cannot be detected.",
            ],
        }
        (run_dir / "analysis.json").write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
        return response
    except Exception:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise
