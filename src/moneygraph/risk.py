"""Deterministic, explainable AML risk hypotheses.

The scores in this module are prioritisation aids, not legal conclusions.
Every score is accompanied by the signals that contributed to it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .features import pct_rank

RISK_LEVELS = (
    (75.0, "critical"),
    (50.0, "high"),
    (25.0, "medium"),
    (0.0, "low"),
)


def risk_level(score: float) -> str:
    for threshold, level in RISK_LEVELS:
        if score >= threshold:
            return level
    return "low"


def _join_factors(factors: list[str]) -> str:
    return " | ".join(factors) if factors else "Существенные сигналы не выявлены"


def compute_risk(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    transactions: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return node, edge and transaction frames enriched with risk fields."""
    node_df = nodes.copy()
    edge_df = edges.copy()
    tx_df = transactions.copy()

    volume_pct = pct_rank(node_df.in_kzt + node_df.out_kzt)
    counterparties_pct = pct_rank(node_df.in_deg + node_df.out_deg)
    activity_pct = pct_rank(node_df.in_tx + node_df.out_tx)
    bridge_pct = pct_rank(node_df.betweenness)
    pass_signal = (
        node_df.pass_through.fillna(0).between(0.8, 1.2).astype(float)
        * (node_df.in_deg.gt(0) & node_df.out_deg.gt(0)).astype(float)
    )
    cycle_signal = node_df.in_cycle.fillna(False).astype(float)
    temporal_signal = (
        node_df.fast_transit.fillna(False).astype(float)
        + node_df.synchronized_burst.fillna(False).astype(float)
    ).clip(upper=1)

    base = (
        0.25 * volume_pct
        + 0.20 * counterparties_pct
        + 0.10 * activity_pct
        + 0.15 * bridge_pct
        + 0.10 * pass_signal
        + 0.10 * cycle_signal
        + 0.10 * temporal_signal
    )

    # A small, bounded neighbourhood signal makes connected high-risk regions
    # visible without allowing one neighbour to dominate the result.
    by_gid = pd.Series(base.values, index=node_df.gid)
    neighbour_values: dict[int, list[float]] = {}
    for row in edge_df.itertuples():
        neighbour_values.setdefault(int(row.src), []).append(float(by_gid.get(row.dst, 0)))
        neighbour_values.setdefault(int(row.dst), []).append(float(by_gid.get(row.src, 0)))
    neighbour_signal = node_df.gid.map(
        lambda gid: float(np.mean(neighbour_values.get(int(gid), [0.0])))
    )
    node_df["risk_score"] = ((0.9 * base + 0.1 * neighbour_signal) * 100).clip(0, 100).round(1)
    node_df["risk_level"] = node_df.risk_score.map(risk_level)

    node_factors: list[str] = []
    for index, row in node_df.iterrows():
        factors: list[str] = []
        if volume_pct.loc[index] >= 0.8:
            factors.append("высокий совокупный объём переводов")
        if counterparties_pct.loc[index] >= 0.8:
            factors.append("много уникальных контрагентов")
        if activity_pct.loc[index] >= 0.8:
            factors.append("высокая транзакционная активность")
        if bridge_pct.loc[index] >= 0.8:
            factors.append("узел связывает части сети")
        if bool(row.in_cycle):
            factors.append("участие в циклическом потоке")
        if bool(row.fast_transit):
            factors.append("быстрый транзит средств")
        if bool(row.synchronized_burst):
            factors.append("синхронные поступления от разных плательщиков")
        if pass_signal.loc[index] > 0:
            factors.append("большая часть входящего объёма уходит дальше")
        if neighbour_signal.loc[index] >= 0.5:
            factors.append("связи с приоритетными узлами")
        node_factors.append(_join_factors(factors))
    node_df["risk_factors"] = node_factors
    node_df["risk_explanation"] = node_df.apply(
        lambda row: (
            f"AML-гипотеза ({row.risk_score:.1f}/100): {row.risk_factors}. "
            "Требуется проверка аналитиком."
        ),
        axis=1,
    )

    node_risk = node_df.set_index("gid").risk_score
    edge_volume_pct = pct_rank(edge_df.sum_kzt)
    edge_activity_pct = pct_rank(edge_df.n_tx.fillna(0))
    endpoint_risk = (
        edge_df.src.map(node_risk).fillna(0) + edge_df.dst.map(node_risk).fillna(0)
    ) / 200
    tx_backed = edge_df.get("has_transactions", pd.Series(True, index=edge_df.index)).astype(bool)
    edge_df["risk_score"] = (
        100
        * (
            0.40 * edge_volume_pct
            + 0.20 * edge_activity_pct
            + 0.35 * endpoint_risk
            + 0.05 * tx_backed.astype(float)
        )
    ).clip(0, 100).round(1)
    edge_df["risk_level"] = edge_df.risk_score.map(risk_level)
    edge_factors: list[str] = []
    for index, row in edge_df.iterrows():
        factors = []
        if edge_volume_pct.loc[index] >= 0.8:
            factors.append("высокий объём по направлению")
        if edge_activity_pct.loc[index] >= 0.8:
            factors.append("много повторных переводов")
        if endpoint_risk.loc[index] >= 0.5:
            factors.append("связь узлов повышенного риска")
        if not bool(tx_backed.loc[index]):
            factors.append("структурная связь без транзакций в выгрузке")
        edge_factors.append(_join_factors(factors))
    edge_df["risk_factors"] = edge_factors
    edge_df["risk_explanation"] = edge_df.apply(
        lambda row: f"AML-гипотеза по связи ({row.risk_score:.1f}/100): {row.risk_factors}.",
        axis=1,
    )

    pair_risk = edge_df.set_index(["src", "dst"]).risk_score
    tx_amount_pct = pct_rank(tx_df.sum_kzt)
    tx_df["risk_score"] = [
        round(
            float(
                0.55 * tx_amount_pct.loc[index] * 100
                + 0.45 * pair_risk.get((row.src, row.dst), 0)
            ),
            1,
        )
        for index, row in tx_df.iterrows()
    ]
    tx_df["risk_level"] = tx_df.risk_score.map(risk_level)
    tx_df["risk_factors"] = [
        _join_factors(
            (["крупная сумма транзакции"] if tx_amount_pct.loc[index] >= 0.8 else [])
            + (["рискованное направление перевода"] if row.risk_score >= 50 else [])
        )
        for index, row in tx_df.iterrows()
    ]
    return node_df, edge_df, tx_df


def enrich_cluster_risk(clusters: pd.DataFrame, nodes: pd.DataFrame) -> pd.DataFrame:
    """Add cluster score, level and explainable factors."""
    out = clusters.copy()
    grouped = nodes.groupby("cluster_id")
    mean_risk = out.cluster_id.map(grouped.risk_score.mean()).fillna(0)
    max_risk = out.cluster_id.map(grouped.risk_score.max()).fillna(0)
    volume_pct = pct_rank(out.sum_kzt_internal)
    seed_pct = pct_rank(out.n_seed)
    out["risk_score"] = (
        0.45 * mean_risk + 0.25 * max_risk + 20 * volume_pct + 10 * seed_pct
    ).clip(0, 100).round(1)
    out["risk_level"] = out.risk_score.map(risk_level)
    factors: list[str] = []
    for index, row in out.iterrows():
        items = []
        if mean_risk.loc[index] >= 50:
            items.append("концентрация узлов повышенного риска")
        if max_risk.loc[index] >= 75:
            items.append("наличие критического узла")
        if volume_pct.loc[index] >= 0.8:
            items.append("высокий внутренний оборот")
        if row.n_seed >= 2:
            items.append("несколько известных seed-узлов")
        factors.append(_join_factors(items))
    out["risk_factors"] = factors
    out["risk_explanation"] = out.apply(
        lambda row: f"AML-гипотеза по кластеру ({row.risk_score:.1f}/100): {row.risk_factors}.",
        axis=1,
    )
    return out
