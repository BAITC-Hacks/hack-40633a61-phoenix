"""Структурные признаки узлов, посчитанные из графа."""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
import networkx as nx

from .config import TH


def pct_rank(s: pd.Series) -> pd.Series:
    """Процентильный ранг признака (0..1), NaN -> 0."""
    return s.rank(pct=True, method="average").fillna(0.0)


def structural_features(graph: nx.DiGraph, nodes: pd.DataFrame) -> pd.DataFrame:
    """Считает in/out степени, обороты, PageRank, betweenness, компоненты,
    pass_through, признак обрыва обхода на 4-м колене и участие в циклах.

    Возвращает ``nodes`` с добавленными колонками (одна строка на ``gid``,
    включая узлы без единого ребра — они получат нулевые метрики).
    """
    in_deg = dict(graph.in_degree())
    out_deg = dict(graph.out_degree())
    in_kzt = dict(graph.in_degree(weight="sum_kzt"))
    out_kzt = dict(graph.out_degree(weight="sum_kzt"))
    in_tx = dict(graph.in_degree(weight="n_tx"))
    out_tx = dict(graph.out_degree(weight="n_tx"))
    pagerank = nx.pagerank(graph, weight="sum_kzt")
    # betweenness невзвешенная: структурная позиция "моста" независимо от суммы
    # (объём денег уже учтён через pagerank/in_kzt/out_kzt отдельно)
    betweenness = nx.betweenness_centrality(graph, weight=None)

    comp_id: dict[int, int] = {}
    for i, comp in enumerate(nx.weakly_connected_components(graph)):
        for node in comp:
            comp_id[node] = i

    df = nodes[["gid", "depth", "is_seed"]].copy()
    df["in_deg"] = df.gid.map(in_deg).fillna(0).astype(int)
    df["out_deg"] = df.gid.map(out_deg).fillna(0).astype(int)
    df["in_kzt"] = df.gid.map(in_kzt).fillna(0.0)
    df["out_kzt"] = df.gid.map(out_kzt).fillna(0.0)
    df["in_tx"] = df.gid.map(in_tx).fillna(0).astype(int)
    df["out_tx"] = df.gid.map(out_tx).fillna(0).astype(int)
    df["pagerank"] = df.gid.map(pagerank).fillna(0.0)
    df["betweenness"] = df.gid.map(betweenness).fillna(0.0)
    df["component_id"] = df.gid.map(comp_id)  # NaN для seed-орфанов без единого ребра
    df["in_component"] = df.component_id.notna()

    df["pass_through"] = np.where(
        df.in_kzt > 0, df.out_kzt / df.in_kzt.replace(0, np.nan), np.nan
    )
    # ЛОВУШКА: depth==4 & out_deg==0 — это обрыв обхода, а не обязательно "деньги осели"
    df["truncated_by_depth"] = (df.depth == 4) & (df.out_deg == 0)

    df["in_cycle"] = df.gid.isin(_find_cycle_nodes(graph))
    return df


def _find_cycle_nodes(graph: nx.DiGraph, time_budget_s: float = 20.0) -> set[int]:
    """Узлы, входящие хотя бы в один возвратный цикл длиной ≤ ``CYCLE_LENGTH_BOUND``.

    Доп. сигнал, не влияет на роль напрямую. Ограничен по времени/количеству
    циклов, чтобы не взорваться на плотных графах.
    """
    in_cycle: set[int] = set()
    t0 = time.time()
    for i, cyc in enumerate(nx.simple_cycles(graph, length_bound=TH["CYCLE_LENGTH_BOUND"])):
        in_cycle.update(cyc)
        if i >= 20000 or time.time() - t0 > time_budget_s:
            break
    return in_cycle
