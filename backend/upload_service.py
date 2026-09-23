"""Safe parquet ingestion, schema inference and isolated analysis runs."""

from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq
from fastapi import UploadFile

from src.moneygraph.pipeline import run

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_ROWS = 500_000
MAX_FILES = 3

ALIASES = {
    "src": ("src", "source", "from"),
    "dst": ("dst", "target", "to"),
    "sum_kzt": ("sum_kzt", "amount", "value"),
    "date": ("date", "timestamp"),
    "tx_id": ("tx_id", "transaction_id", "transaction id", "id"),
    "gid": ("gid", "node_id", "account_id"),
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
        if len(matches) > 1:
            raise UploadValidationError(
                f"Ambiguous columns for {canonical}: {', '.join(matches)}. Keep only one supported alias."
            )
        if matches:
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


async def save_and_inspect(files: list[UploadFile], incoming_dir: Path) -> list[IngestedFile]:
    if not 1 <= len(files) <= MAX_FILES:
        raise UploadValidationError(f"Upload 1 to {MAX_FILES} parquet files.")
    incoming_dir.mkdir(parents=True, exist_ok=False)
    results: list[IngestedFile] = []
    kinds: set[str] = set()
    for index, upload in enumerate(files):
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
        if kind in kinds:
            raise UploadValidationError(f"More than one file inferred as {kind}.")
        kinds.add(kind)
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


def _normalize_ids(frames: list[pd.DataFrame]) -> dict[str, int]:
    values: list[str] = []
    for frame in frames:
        for column in ("gid", "src", "dst"):
            if column in frame:
                if frame[column].isna().any():
                    raise UploadValidationError(f"{column} contains null identifiers.")
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
    tx = _rename(_read(by_kind["transactions"]), by_kind["transactions"]) if "transactions" in by_kind else None
    edges = _rename(_read(by_kind["edges"]), by_kind["edges"]) if "edges" in by_kind else None
    nodes = _rename(_read(by_kind["nodes"]), by_kind["nodes"]) if "nodes" in by_kind else None

    if tx is None:
        raise UploadValidationError(
            "A transactions parquet is required. It must include src/source/from, "
            "dst/target/to, amount/sum_kzt/value and date/timestamp."
        )
    _normalize_amounts(tx, "transactions")
    tx["date"] = pd.to_datetime(tx["date"], errors="coerce", utc=True).dt.tz_localize(None)
    if tx["date"].isna().any():
        raise UploadValidationError("transactions: date/timestamp contains invalid or missing dates.")
    if "tx_id" not in tx:
        tx["tx_id"] = [f"tx-{i + 1}" for i in range(len(tx))]
    if tx["tx_id"].isna().any() or tx["tx_id"].astype(str).duplicated().any():
        raise UploadValidationError("transactions: transaction id must be non-null and unique when provided.")

    if edges is not None:
        _normalize_amounts(edges, "edges")
        if "n_tx" not in edges:
            edges["n_tx"] = 1
        if "depth" not in edges:
            edges["depth"] = 1
        edges["n_tx"] = pd.to_numeric(edges["n_tx"], errors="coerce").fillna(1).astype(int)
        edges["depth"] = pd.to_numeric(edges["depth"], errors="coerce").fillna(1).astype(int)
    if nodes is not None:
        if "is_seed" not in nodes:
            nodes["is_seed"] = False
        nodes["is_seed"] = nodes["is_seed"].fillna(False).astype(bool)
        if "depth" not in nodes:
            nodes["depth"] = 0
        nodes["depth"] = pd.to_numeric(nodes["depth"], errors="coerce").fillna(0).astype(int)

    frames = [frame for frame in (tx, edges, nodes) if frame is not None]
    id_mapping = _normalize_ids(frames)
    if edges is None:
        edges = tx.groupby(["src", "dst"], as_index=False).agg(sum_kzt=("sum_kzt", "sum"), n_tx=("sum_kzt", "size"))
        edges["depth"] = 1
    if nodes is None:
        gids = pd.unique(pd.concat([tx["src"], tx["dst"]], ignore_index=True))
        nodes = pd.DataFrame({"gid": gids, "depth": 0, "is_seed": False})

    known = set(nodes["gid"])
    referenced = set(tx["src"]) | set(tx["dst"]) | set(edges["src"]) | set(edges["dst"])
    missing = referenced - known
    if missing:
        nodes = pd.concat(
            [nodes, pd.DataFrame({"gid": sorted(missing), "depth": 0, "is_seed": False})],
            ignore_index=True,
        )
    nodes = nodes[["gid", "depth", "is_seed"]].drop_duplicates("gid")
    edges = edges[["src", "dst", "sum_kzt", "n_tx", "depth"]]
    tx = tx[["tx_id", "src", "dst", "sum_kzt", "date"]]

    data_dir.mkdir(parents=True, exist_ok=False)
    nodes.to_parquet(data_dir / "nodes.parquet", index=False)
    edges.to_parquet(data_dir / "edges.parquet", index=False)
    tx.to_parquet(data_dir / "transactions.parquet", index=False)
    mapped = any(str(value) != str(mapped_value) for value, mapped_value in id_mapping.items())
    if mapped:
        (data_dir / "id_mapping.json").write_text(json.dumps(id_mapping, ensure_ascii=False), encoding="utf-8")
    return {
        "nodes": len(nodes),
        "edges": len(edges),
        "transactions": len(tx),
        "ids_remapped": mapped,
        "date_min": tx["date"].min().isoformat(),
        "date_max": tx["date"].max().isoformat(),
    }


async def create_analysis(files: list[UploadFile], runs_dir: Path) -> dict[str, Any]:
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
