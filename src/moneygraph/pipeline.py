"""Оркестратор: сырые .parquet -> роли, кластеры, приоритеты, визуализация.

Единственная точка входа для полного пересчёта. Каждый шаг — вызов функции
из соответствующего модуля, никакой аналитической логики здесь самой нет.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from .clustering import build_clusters_table, cluster_nodes
from .exports import write_analysis_notes, write_outputs
from .features import structural_features
from .graph import build_graph
from .loading import DataLoadError, load, sanity_check
from .priority import build_top_nodes, compute_priority
from .risk import compute_risk, enrich_cluster_risk
from .roles import assign_roles
from .temporal import temporal_features

__all__ = ["run", "DataLoadError"]


def run(data_dir: Path, out_dir: Path, build_viewer: bool = True) -> pd.DataFrame:
    """Полный пересчёт: parquet -> ``out/*.csv`` + ``graph.html``.

    Returns:
        Итоговый датафрейм узлов со всеми признаками, ролями и приоритетом
        (то же самое, что попадает в ``nodes_roles.csv`` плюс служебные поля).
    """
    t_start = time.time()
    raw = load(data_dir)
    sanity_check(raw)

    graph = build_graph(raw.edges)
    df = structural_features(graph, raw.nodes)

    temp = temporal_features(raw.tx, df.gid)
    df = df.merge(temp, on="gid", how="left")

    df["cluster_id"] = cluster_nodes(graph, df).values

    df = assign_roles(df)
    df = compute_priority(df)

    df, risk_edges, risk_transactions = compute_risk(df, raw.edges, raw.tx)
    clusters = enrich_cluster_risk(build_clusters_table(df, risk_edges), df)
    top_nodes = build_top_nodes(df, n=40)

    write_outputs(df, clusters, top_nodes, risk_edges, risk_transactions, out_dir)
    write_analysis_notes(df, graph, out_dir)

    elapsed = time.time() - t_start
    print(f"\nПолный пересчёт занял {elapsed:.1f} сек (лимит 5 мин).")

    if build_viewer:
        from . import viewer
        viewer.build(df, raw.edges, clusters, out_dir)

    print("\nПроверка ролей (распределение):")
    print(df.role.value_counts().to_string())
    return df
