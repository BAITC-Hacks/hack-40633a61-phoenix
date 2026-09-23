"""Louvain-кластеризация и построение таблицы кластеров с гипотезами."""

from __future__ import annotations

import pandas as pd
import networkx as nx


def cluster_nodes(graph: nx.DiGraph, df: pd.DataFrame) -> pd.Series:
    """Louvain на неориентированной проекции. Направление здесь намеренно не
    учитывается (это метод для сообществ, а не для ролей — см. README)."""
    ug = graph.to_undirected()
    communities = nx.community.louvain_communities(ug, weight="sum_kzt", seed=42)
    communities = sorted(communities, key=len, reverse=True)

    cluster_id = pd.Series(index=df.gid, dtype="int64")
    for cid, members in enumerate(communities):
        for gid in members:
            cluster_id[gid] = cid

    # Seed-узлы без единого ребра не попадают в проекцию Louvain вовсе —
    # это не "их собственные микрокластеры", а честная категория "нет данных
    # о движении средств". Отдельный служебный кластер.
    orphan_cluster = len(communities)
    cluster_id = cluster_id.reindex(df.gid)
    cluster_id = cluster_id.fillna(orphan_cluster).astype(int)
    return cluster_id


def build_clusters_table(df: pd.DataFrame, edges: pd.DataFrame) -> pd.DataFrame:
    """Одна строка на кластер: размер, seed'ы, внутренний оборот, гипотеза."""
    rows = []
    for cid, group in df.groupby("cluster_id"):
        members = set(group.gid)
        internal = edges[edges.src.isin(members) & edges.dst.isin(members)]
        top_gids = (
            group.sort_values("priority_score", ascending=False)
            .head(5)["gid"].astype(str).tolist()
        )
        n_seed = int(group.is_seed.sum())
        n_nodes = len(group)
        is_orphan_cluster = (group.in_deg.eq(0) & group.out_deg.eq(0)).all()

        hyp = _hypothesis(group, n_seed, n_nodes, is_orphan_cluster)

        rows.append(dict(
            cluster_id=int(cid),
            n_nodes=n_nodes,
            n_seed=n_seed,
            sum_kzt_internal=round(float(internal.sum_kzt.sum()), 2),
            top_gids=";".join(top_gids),
            hypothesis=hyp,
        ))
    out = pd.DataFrame(rows).sort_values("n_nodes", ascending=False).reset_index(drop=True)
    return out


def _hypothesis(group: pd.DataFrame, n_seed: int, n_nodes: int, is_orphan_cluster: bool) -> str:
    if is_orphan_cluster:
        return (
            f"Служебная группа: {n_nodes} seed-клиентов без единого ребра в выборке "
            f"(0 входящих и исходящих) — операции вне банка или ниже порога 5 000 KZT."
        )
    if n_nodes < 3:
        return f"Микрофрагмент сети ({n_nodes} узл.), изолированный от основной массы переводов."

    role_counts = group.role.value_counts()
    dominant = role_counts.idxmax()

    if n_seed >= 2 and dominant in ("consolidator", "coordinator"):
        return (
            f"Ядро с несколькими seed-клиентами ({n_seed} из {n_nodes}) и явными узлами "
            f"консолидации/координации — вероятная организационная группа, а не случайные попутчики."
        )
    if dominant == "distributor":
        return (
            f"Кластер веерного распределения: доминирует роль distributor "
            f"({role_counts.get('distributor', 0)} из {n_nodes} узлов) — похоже на сеть выплат вниз по цепочке."
        )
    if n_seed >= 2:
        return (
            f"{n_seed} seed-клиентов из {n_nodes} узлов задействованы в одной сети переводов — "
            f"общая инфраструктура, а не независимые эпизоды."
        )
    return (
        f"Периферийный фрагмент вокруг {n_seed} seed-клиента, {n_nodes} узлов, "
        f"выраженной консолидации не обнаружено."
    )
