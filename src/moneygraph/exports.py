"""Запись всех выгрузок пайплайна: CSV, JSON и analysis_notes.md."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import networkx as nx

from .config import NODES_ROLES_REQUIRED_COLUMNS

EXTRA_NODE_COLUMNS = [
    "in_deg", "out_deg", "in_kzt", "out_kzt", "in_tx", "out_tx",
    "pagerank", "betweenness", "pass_through", "depth", "is_seed",
    "truncated_by_depth", "in_cycle", "median_lag_days",
    "max_same_day_payers", "fast_transit", "synchronized_burst",
    "risk_score", "risk_level", "risk_factors", "risk_explanation",
]


def write_outputs(
    df: pd.DataFrame,
    clusters: pd.DataFrame,
    top_nodes: pd.DataFrame,
    edges: pd.DataFrame,
    transactions: pd.DataFrame,
    out_dir: Path,
) -> None:
    """Пишет ``nodes_roles.csv``, ``clusters.csv``, ``top_nodes.csv``,
    ``graph_export.json`` в ``out_dir`` (создаёт папку при необходимости)."""
    out_dir.mkdir(parents=True, exist_ok=True)

    cols = NODES_ROLES_REQUIRED_COLUMNS + [c for c in EXTRA_NODE_COLUMNS if c in df.columns]
    nodes_roles = df[cols].copy()
    nodes_roles.to_csv(out_dir / "nodes_roles.csv", index=False)

    clusters.to_csv(out_dir / "clusters.csv", index=False)
    top_nodes.to_csv(out_dir / "top_nodes.csv", index=False)
    transactions.to_parquet(out_dir / "transactions_enriched.parquet", index=False)

    _write_graph_json(df, edges, transactions, out_dir)

    print(f"\nВыгрузки записаны в {out_dir}/:")
    print(f"  nodes_roles.csv   : {len(nodes_roles)} строк")
    print(f"  clusters.csv      : {len(clusters)} строк")
    print(f"  top_nodes.csv     : {len(top_nodes)} строк")


def _json_value(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def _write_graph_json(
    df: pd.DataFrame,
    edges: pd.DataFrame,
    transactions: pd.DataFrame,
    out_dir: Path,
) -> None:
    role_lookup = df.set_index("gid").to_dict(orient="index")
    graph_nodes = []
    for gid, attrs in role_lookup.items():
        graph_nodes.append(dict(
            id=int(gid), role=attrs["role"], role_score=float(attrs["role_score"]),
            cluster_id=int(attrs["cluster_id"]), priority_score=float(attrs["priority_score"]),
            evidence=attrs["evidence"], is_seed=bool(attrs["is_seed"]), depth=int(attrs["depth"]),
            in_kzt=float(attrs["in_kzt"]), out_kzt=float(attrs["out_kzt"]),
            in_deg=int(attrs["in_deg"]), out_deg=int(attrs["out_deg"]),
            in_tx=int(attrs["in_tx"]), out_tx=int(attrs["out_tx"]),
            risk_score=float(attrs["risk_score"]), risk_level=attrs["risk_level"],
            risk_factors=attrs["risk_factors"], risk_explanation=attrs["risk_explanation"],
        ))

    tx_groups: dict[tuple[int, int], dict[str, Any]] = {}
    for (src, dst), group in transactions.groupby(["src", "dst"], sort=False):
        ordered = group.sort_values("date", ascending=False)
        tx_groups[(int(src), int(dst))] = {
            "tx_ids": [_json_value(value) for value in ordered.tx_id.tolist()],
            "first_date": _json_value(group.date.min()),
            "last_date": _json_value(group.date.max()),
        }

    graph_edges = []
    for row in edges.itertuples():
        tx_meta = tx_groups.get((int(row.src), int(row.dst)), {})
        graph_edges.append(
            {
                "id": f"{int(row.src)}:{int(row.dst)}",
                "source": int(row.src),
                "target": int(row.dst),
                "sum_kzt": float(row.sum_kzt),
                "n_tx": int(row.n_tx),
                "has_transactions": bool(getattr(row, "has_transactions", True)),
                "tx_ids": tx_meta.get("tx_ids", []),
                "first_date": tx_meta.get("first_date"),
                "last_date": tx_meta.get("last_date"),
                "risk_score": float(row.risk_score),
                "risk_level": row.risk_level,
                "risk_factors": row.risk_factors,
                "risk_explanation": row.risk_explanation,
            }
        )
    with open(out_dir / "graph_export.json", "w", encoding="utf-8") as f:
        json.dump(dict(nodes=graph_nodes, edges=graph_edges), f, ensure_ascii=False)
    print(f"  graph_export.json : {len(graph_nodes)} узлов, {len(graph_edges)} рёбер")


def write_analysis_notes(df: pd.DataFrame, graph: nx.DiGraph, out_dir: Path) -> None:
    """Пишет ``analysis_notes.md`` — устойчивость сети, циклы, синхронные
    платежи, пробелы в данных (для демо и для AI-ассистента как контекст)."""
    lines = ["# Дополнительные наблюдения (авто-сгенерировано pipeline)\n"]

    lines.append("## Устойчивость сети (что если изъять топ-N приоритетных узлов)\n")
    for topn in (10, 20, 30):
        remove = set(df.sort_values("priority_score", ascending=False).head(topn).gid)
        h = graph.copy()
        h.remove_nodes_from(remove & set(h.nodes()))
        comps = list(nx.weakly_connected_components(h)) if h.number_of_nodes() else []
        giant = max((len(c) for c in comps), default=0)
        lines.append(
            f"- Изъятие топ-{topn}: {h.number_of_nodes()} узлов остаётся, "
            f"{len(comps)} компонент связности, крупнейшая — {giant} узлов "
            f"(было {nx.number_weakly_connected_components(graph)} компонент / "
            f"{max((len(c) for c in nx.weakly_connected_components(graph)), default=0)} в крупнейшей)."
        )

    lines.append("\n## Возвратные потоки (циклы длиной до 6)\n")
    n_cycle_nodes = int(df.in_cycle.sum())
    lines.append(f"- Узлов, входящих хотя бы в один цикл до 6 переводов: {n_cycle_nodes}.")

    lines.append("\n## Синхронные платежи и быстрый транзит\n")
    if "synchronized_burst" in df.columns:
        n_burst = int(df.synchronized_burst.sum())
        n_fast = int(df.fast_transit.sum())
        lines.append(f"- Узлов с 3+ разными плательщиками в один день: {n_burst}.")
        lines.append(f"- Узлов с медианной задержкой приём→отправка ≤ 2 дней: {n_fast}.")

    n_truncated = int(df.truncated_by_depth.sum()) if "truncated_by_depth" in df.columns else 0
    lines.append("\n## Полнота данных / что запросить дальше\n")
    lines.append(
        "- Seed-клиенты без единого ребра в edges (нет ни одного перевода в выборке) — "
        "стоит запросить их движения по счёту вне периода/банка."
    )
    lines.append(
        f"- Обрыв на 4-м колене у {n_truncated} узлов — для узлов с высоким in_deg среди них "
        "(классифицированы как consolidator с пониженным role_score) стоит запросить "
        "исходящие переводы на 5-м колене."
    )
    lines.append(
        "- Транзакции < 5 000 KZT не в выборке — возможное дробление сумм ниже порога "
        "не видно; стоит запросить сырые транзакции без порога для топ-приоритетных gid."
    )

    with open(out_dir / "analysis_notes.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("  analysis_notes.md : доп. наблюдения для демо")
