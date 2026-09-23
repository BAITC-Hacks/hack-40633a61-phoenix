"""Сборка направленного взвешенного графа NetworkX из таблицы рёбер."""

from __future__ import annotations

import pandas as pd
import networkx as nx


def build_graph(edges: pd.DataFrame) -> nx.DiGraph:
    """Строит ``DiGraph``: вес ребра — ``sum_kzt`` (для PageRank), плюс
    ``n_tx`` и ``depth`` как атрибуты ребра."""
    graph = nx.DiGraph()
    for r in edges.itertuples(index=False):
        graph.add_edge(r.src, r.dst, sum_kzt=float(r.sum_kzt), n_tx=int(r.n_tx), depth=int(r.depth))
    return graph
