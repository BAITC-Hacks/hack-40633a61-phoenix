#!/usr/bin/env python3
"""
Граф денег — HackAlem AI.
Единая точка входа: сырые .parquet -> роли, кластеры, приоритеты, визуализация.

Запуск:
    python src/pipeline.py --data data --out out

Пайплайн:
    1. Загрузка edges/nodes/transactions.parquet, проверка консистентности.
    2. Сборка направленного взвешенного графа NetworkX.
    3. Структурные метрики: степени, обороты, PageRank, betweenness, циклы,
       компоненты связности.
    4. Временные метрики из transactions.parquet: медианная задержка
       "получил -> отправил дальше", максимальная синхронность входящих
       платежей в один день.
    5. Присвоение роли каждому узлу по явным, документированным правилам
       (см. README, раздел "Критерии ролей").
    6. Кластеризация (Louvain, неориентированная проекция) + гипотеза по
       каждому кластеру.
    7. priority_score — кого аналитику смотреть первым.
    8. Выгрузки: out/nodes_roles.csv, out/clusters.csv, out/top_nodes.csv,
       out/graph_export.json, out/analysis_notes.md, out/graph.html (граф).

Все пороги — числа, объяснены в README. Ни один gid нигде не зашит.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import networkx as nx

ROLES = ["coordinator", "consolidator", "distributor", "transit", "terminal", "peripheral"]

# ---------------------------------------------------------------------------
# Пороги (данные -> число). Обоснование каждого — в README ("Критерии ролей").
# ---------------------------------------------------------------------------
TH = dict(
    CONSOLIDATOR_IN_DEG=8,     # 90-й+ перцентиль in_deg среди узлов с in_deg>0 (17 узлов, диапазон 8-24)
    DISTRIBUTOR_OUT_DEG=10,    # верхние ~9% узлов с исходящими (64 узла, до 116 получателей)
    COORDINATOR_IN_DEG=8,      # = CONSOLIDATOR_IN_DEG
    COORDINATOR_OUT_DEG=10,    # = DISTRIBUTOR_OUT_DEG -> пересечение даёт 9 узлов-кандидатов
    TRANSIT_PASS_LOW=0.8,      # окно pass_through, где деньги "проходят, не оседая"
    TRANSIT_PASS_HIGH=1.2,
    FAST_TRANSIT_DAYS=2,       # медианная задержка приём->отправка <= N дней => "быстрый транзит"
    BURST_PAYERS=3,            # 3+ разных плательщика в один день => синхронный платёж (evidence бонус)
    CYCLE_LENGTH_BOUND=6,
    MIN_CLUSTER_STABLE=5,      # кластер с 5+ узлами считаем "устойчивым" при интерпретации
)


# =============================================================== загрузка ===

def load(data_dir: Path):
    edges = pd.read_parquet(data_dir / "edges.parquet")
    nodes = pd.read_parquet(data_dir / "nodes.parquet")
    tx = pd.read_parquet(data_dir / "transactions.parquet")
    tx["date"] = pd.to_datetime(tx["date"])
    return edges, nodes, tx


def sanity_check(edges, nodes, tx) -> None:
    print("=" * 70)
    print("ПРОВЕРКА ДАННЫХ")
    print("=" * 70)
    print(f"  узлов в nodes.parquet : {len(nodes):>6}")
    print(f"  рёбер                 : {len(edges):>6}")
    print(f"  транзакций            : {len(tx):>6}")
    print(f"  seed-клиентов         : {int(nodes.is_seed.sum()):>6}")
    print(f"  оборот, KZT           : {edges.sum_kzt.sum():>14,.0f}")
    print(f"  период                : {tx.date.min().date()} — {tx.date.max().date()}")

    agg = tx.groupby(["src", "dst"]).agg(s=("sum_kzt", "sum"), c=("sum_kzt", "size")).reset_index()
    m = edges.merge(agg, on=["src", "dst"], how="outer", indicator=True)
    assert (m._merge == "both").all(), "edges и transactions не сходятся по парам"
    print("  edges == transactions : OK")

    in_edges = set(edges.src) | set(edges.dst)
    orphans = set(nodes.gid) - in_edges
    print(f"  узлов без единого ребра: {len(orphans)} (из них seed: "
          f"{len(orphans & set(nodes[nodes.is_seed].gid))})")
    print("=" * 70)


# ==================================================================== граф ===

def build_graph(edges: pd.DataFrame) -> nx.DiGraph:
    G = nx.DiGraph()
    for r in edges.itertuples(index=False):
        G.add_edge(r.src, r.dst, sum_kzt=float(r.sum_kzt), n_tx=int(r.n_tx), depth=int(r.depth))
    return G


# ================================================================ признаки ===

def structural_features(G: nx.DiGraph, nodes: pd.DataFrame) -> pd.DataFrame:
    in_deg = dict(G.in_degree())
    out_deg = dict(G.out_degree())
    in_kzt = dict(G.in_degree(weight="sum_kzt"))
    out_kzt = dict(G.out_degree(weight="sum_kzt"))
    in_tx = dict(G.in_degree(weight="n_tx"))
    out_tx = dict(G.out_degree(weight="n_tx"))
    pagerank = nx.pagerank(G, weight="sum_kzt")
    # betweenness невзвешенная: структурная позиция "моста" независимо от суммы
    # (объём денег уже учтён через pagerank/in_kzt/out_kzt отдельно)
    betweenness = nx.betweenness_centrality(G, weight=None)

    comp_id = {}
    for i, comp in enumerate(nx.weakly_connected_components(G)):
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
    df["component_id"] = df.gid.map(comp_id)  # NaN для 19 seed-орфанов без единого ребра
    df["in_component"] = df.component_id.notna()

    df["pass_through"] = np.where(
        df.in_kzt > 0, df.out_kzt / df.in_kzt.replace(0, np.nan), np.nan
    )
    # ЛОВУШКА: depth==4 & out_deg==0 — это обрыв обхода, а не обязательно "деньги осели"
    df["truncated_by_depth"] = (df.depth == 4) & (df.out_deg == 0)

    # циклы (возвратные потоки) — доп. сигнал, не влияет на роль напрямую
    in_cycle = set()
    t0 = time.time()
    for i, cyc in enumerate(nx.simple_cycles(G, length_bound=TH["CYCLE_LENGTH_BOUND"])):
        in_cycle.update(cyc)
        if i >= 20000 or time.time() - t0 > 20:
            break
    df["in_cycle"] = df.gid.isin(in_cycle)

    return df


def temporal_features(tx: pd.DataFrame, gids: pd.Series) -> pd.DataFrame:
    """Задержка приём->отправка и синхронность входящих платежей за день."""
    tx = tx.copy()
    in_by_node = tx.groupby("dst")["date"].apply(lambda s: sorted(s.tolist()))
    out_by_node = tx.groupby("src")["date"].apply(lambda s: sorted(s.tolist()))
    burst_by_node = (
        tx.groupby(["dst", "date"])["src"].nunique().groupby("dst").max()
    )

    lag_days = {}
    for gid in set(in_by_node.index) & set(out_by_node.index):
        ins = in_by_node[gid]
        outs = out_by_node[gid]
        gaps = []
        j = 0
        for d_in in ins:
            while j < len(outs) and outs[j] < d_in:
                j += 1
            if j < len(outs):
                gaps.append((outs[j] - d_in).days)
        if gaps:
            lag_days[gid] = float(np.median(gaps))

    out = pd.DataFrame({"gid": gids})
    out["median_lag_days"] = out.gid.map(lag_days)
    out["max_same_day_payers"] = out.gid.map(burst_by_node).fillna(0).astype(int)
    out["fast_transit"] = out.median_lag_days.notna() & (
        out.median_lag_days <= TH["FAST_TRANSIT_DAYS"]
    )
    out["synchronized_burst"] = out.max_same_day_payers >= TH["BURST_PAYERS"]
    return out


# ============================================================= кластеры ===

def cluster_nodes(G: nx.DiGraph, df: pd.DataFrame) -> pd.Series:
    """Louvain на неориентированной проекции. Направление здесь намеренно не
    учитывается (это метод для сообществ, а не для ролей — см. README)."""
    UG = G.to_undirected()
    communities = nx.community.louvain_communities(UG, weight="sum_kzt", seed=42)
    communities = sorted(communities, key=len, reverse=True)

    cluster_id = pd.Series(index=df.gid, dtype="int64")
    for cid, members in enumerate(communities):
        for gid in members:
            cluster_id[gid] = cid

    # 19 seed-узлов без единого ребра не попадают в проекцию Louvain вовсе —
    # это не "их собственные микрокластеры", а честная категория "нет данных
    # о движении средств". Отдельный служебный кластер.
    orphan_cluster = len(communities)
    cluster_id = cluster_id.reindex(df.gid)
    cluster_id = cluster_id.fillna(orphan_cluster).astype(int)
    return cluster_id


def build_clusters_table(df: pd.DataFrame, edges: pd.DataFrame) -> pd.DataFrame:
    rows = []
    gid_to_cluster = df.set_index("gid").cluster_id
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

        if is_orphan_cluster:
            hyp = (
                f"Служебная группа: {n_nodes} seed-клиентов без единого ребра в выборке "
                f"(0 входящих и исходящих) — операции вне банка или ниже порога 5 000 KZT."
            )
        elif n_nodes < 3:
            hyp = f"Микрофрагмент сети ({n_nodes} узл.), изолированный от основной массы переводов."
        else:
            role_counts = group.role.value_counts()
            dominant = role_counts.idxmax()
            share_seed = n_seed / n_nodes
            if n_seed >= 2 and dominant in ("consolidator", "coordinator"):
                hyp = (
                    f"Ядро с несколькими seed-клиентами ({n_seed} из {n_nodes}) и явными узлами "
                    f"консолидации/координации — вероятная организационная группа, а не случайные попутчики."
                )
            elif dominant == "distributor":
                hyp = (
                    f"Кластер веерного распределения: доминирует роль distributor "
                    f"({role_counts.get('distributor', 0)} из {n_nodes} узлов) — похоже на сеть выплат вниз по цепочке."
                )
            elif n_seed >= 2:
                hyp = (
                    f"{n_seed} seed-клиентов из {n_nodes} узлов задействованы в одной сети переводов — "
                    f"общая инфраструктура, а не независимые эпизоды."
                )
            else:
                hyp = (
                    f"Периферийный фрагмент вокруг {n_seed} seed-клиента, {n_nodes} узлов, "
                    f"выраженной консолидации не обнаружено."
                )

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


# ================================================================= роли ===

def assign_roles(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    role = pd.Series("peripheral", index=df.index, dtype=object)
    role_score = pd.Series(0.3, index=df.index, dtype=float)
    evidence = pd.Series("", index=df.index, dtype=object)

    def sigmoid_conf(x, k=0.15, mid=0.0):
        return float(1 / (1 + np.exp(-k * (x - mid))))

    for i, r in df.iterrows():
        seed_note = " (seed: входящие занижены — граф собран от него)" if r.is_seed else ""
        is_coord = r.in_deg >= TH["COORDINATOR_IN_DEG"] and r.out_deg >= TH["COORDINATOR_OUT_DEG"]
        is_consol = r.in_deg >= TH["CONSOLIDATOR_IN_DEG"]
        is_distrib = r.out_deg >= TH["DISTRIBUTOR_OUT_DEG"]
        is_transit = (
            r.in_deg >= 1 and r.out_deg >= 1
            and pd.notna(r.pass_through)
            and TH["TRANSIT_PASS_LOW"] <= r.pass_through <= TH["TRANSIT_PASS_HIGH"]
        )

        if r.in_deg == 0 and r.out_deg == 0:
            role.at[i] = "peripheral"
            role_score.at[i] = 0.2
            evidence.at[i] = (
                f"Seed-клиент без единого ребра в выборке — 0 входящих и исходящих переводов "
                f"(порог 5 000 KZT или операции вне банка)."
            )
            continue

        if is_coord:
            role.at[i] = "coordinator"
            role_score.at[i] = round(min(0.95, sigmoid_conf(r.in_deg + r.out_deg, k=0.08, mid=25)), 2)
            evidence.at[i] = (
                f"Одновременно принимает от {r.in_deg} плательщиков ({r.in_kzt:,.0f} KZT) и "
                f"рассылает {r.out_deg} получателям ({r.out_kzt:,.0f} KZT) — двусторонний хаб, "
                f"кандидат в организаторы.{seed_note}"
            )[:200]
        elif is_consol:
            if r.truncated_by_depth:
                role.at[i] = "consolidator"
                role_score.at[i] = round(min(0.65, sigmoid_conf(r.in_deg, k=0.2, mid=10)), 2)
                evidence.at[i] = (
                    f"На 4-м колене получает от {r.in_deg} плательщиков ({r.in_kzt:,.0f} KZT); "
                    f"исходящие переводы за пределами выборки не видны — вероятная точка "
                    f"консолидации, не подтверждено."
                )[:200]
            else:
                role.at[i] = "consolidator"
                role_score.at[i] = round(min(0.95, sigmoid_conf(r.in_deg, k=0.15, mid=12)), 2)
                pt_txt = f", уходит дальше {r.pass_through*100:.0f}%" if pd.notna(r.pass_through) else ""
                evidence.at[i] = (
                    f"Получает от {r.in_deg} разных плательщиков ({r.in_kzt:,.0f} KZT){pt_txt} — "
                    f"точка накопления средств.{seed_note}"
                )[:200]
        elif is_distrib:
            role.at[i] = "distributor"
            role_score.at[i] = round(min(0.95, sigmoid_conf(r.out_deg, k=0.08, mid=20)), 2)
            evidence.at[i] = (
                f"Рассылает {r.out_deg} получателям ({r.out_kzt:,.0f} KZT), получая лишь от "
                f"{r.in_deg} плательщиков — веерное распределение средств вниз по цепочке.{seed_note}"
            )[:200]
        elif is_transit:
            role.at[i] = "transit"
            closeness = 1 - min(abs(r.pass_through - 1.0) / 0.2, 1.0)
            role_score.at[i] = round(0.5 + 0.4 * closeness, 2)
            lag_txt = ""
            if pd.notna(r.get("median_lag_days", np.nan)):
                lag_txt = f", медианная задержка {r.median_lag_days:.0f} дн."
            evidence.at[i] = (
                f"Пропускает средства не удерживая: получил {r.in_kzt:,.0f} KZT, отдал "
                f"{r.out_kzt:,.0f} KZT ({r.pass_through:.2f}x) от {r.in_deg} плательщиков "
                f"{r.out_deg} получателям{lag_txt}.{seed_note}"
            )[:200]
        elif r.out_deg == 0:
            if r.truncated_by_depth:
                role.at[i] = "terminal"
                role_score.at[i] = round(min(0.55, 0.3 + 0.03 * r.in_deg), 2)
                evidence.at[i] = (
                    f"Обрыв обхода на 4-м колене: исходящие за пределами выборки не видны. "
                    f"Получил {r.in_kzt:,.0f} KZT от {r.in_deg} плательщиков — возможный, но "
                    f"не подтверждённый конечный получатель."
                )[:200]
            else:
                role.at[i] = "terminal"
                role_score.at[i] = round(min(0.95, 0.7 + 0.02 * r.in_deg), 2)
                evidence.at[i] = (
                    f"Нет исходящих переводов на {int(r.depth)}-м колене (обход не был "
                    f"искусственно прерван, глубина < 4) — получил {r.in_kzt:,.0f} KZT от "
                    f"{r.in_deg} плательщиков и удержал их."
                )[:200]
        else:
            role.at[i] = "peripheral"
            pt_txt = f", pass_through={r.pass_through:.2f}" if pd.notna(r.pass_through) else ""
            role_score.at[i] = round(0.3 + 0.05 * min(r.in_deg + r.out_deg, 4), 2)
            evidence.at[i] = (
                f"Низкая активность в выборке: {r.in_deg} вход. / {r.out_deg} исход., "
                f"{(r.in_kzt + r.out_kzt):,.0f} KZT суммарно{pt_txt} — выраженных признаков "
                f"роли не выявлено."
            )[:200]

    df["role"] = role
    df["role_score"] = role_score
    df["evidence"] = evidence
    return df


# ============================================================ приоритет ===

def pct_rank(s: pd.Series) -> pd.Series:
    return s.rank(pct=True, method="average").fillna(0.0)


ROLE_WEIGHT = {
    "coordinator": 1.00,
    "consolidator": 0.85,
    "distributor": 0.75,
    "transit": 0.40,
    "terminal": 0.30,
    "peripheral": 0.10,
}


def compute_priority(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    role_w = df.role.map(ROLE_WEIGHT).fillna(0.1)
    pr_pct = pct_rank(df.pagerank)
    vol_pct = pct_rank(df.in_kzt + df.out_kzt)
    bw_pct = pct_rank(df.betweenness)
    # известные 81 seed уже в поле зрения аналитика — небольшой бонус за "новизну"
    # смещает фокус на реальные точки консолидации, а не на уже известных курьеров
    novelty = np.where(df.is_seed, 0.0, 1.0)

    raw = 0.35 * role_w + 0.25 * pr_pct + 0.20 * vol_pct + 0.15 * bw_pct + 0.05 * novelty
    df["priority_score"] = raw.clip(0, 1).round(4)
    return df


def build_top_nodes(df: pd.DataFrame, n: int = 40) -> pd.DataFrame:
    top = df.sort_values("priority_score", ascending=False).head(n).reset_index(drop=True)
    rows = []
    for i, r in top.iterrows():
        why = (
            f"{r.role} (score {r.role_score:.2f}), priority {r.priority_score:.2f}. "
            f"{r.evidence}"
        )[:240]
        rows.append(dict(rank=i + 1, gid=int(r.gid), role=r.role,
                          priority_score=r.priority_score, why=why))
    return pd.DataFrame(rows)


# ============================================================== выгрузки ===

def write_outputs(df: pd.DataFrame, clusters: pd.DataFrame, top_nodes: pd.DataFrame,
                   G: nx.DiGraph, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    roles_cols = ["gid", "role", "role_score", "cluster_id", "priority_score", "evidence"]
    extra_cols = ["in_deg", "out_deg", "in_kzt", "out_kzt", "in_tx", "out_tx",
                  "pagerank", "betweenness", "pass_through", "depth", "is_seed",
                  "truncated_by_depth", "in_cycle", "median_lag_days",
                  "max_same_day_payers", "fast_transit", "synchronized_burst"]
    nodes_roles = df[roles_cols + [c for c in extra_cols if c in df.columns]].copy()
    nodes_roles.to_csv(out_dir / "nodes_roles.csv", index=False)

    clusters.to_csv(out_dir / "clusters.csv", index=False)
    top_nodes.to_csv(out_dir / "top_nodes.csv", index=False)

    # JSON-экспорт для интерфейса просмотра
    role_lookup = df.set_index("gid").to_dict(orient="index")
    graph_nodes = []
    for gid, attrs in role_lookup.items():
        graph_nodes.append(dict(
            id=int(gid), role=attrs["role"], role_score=float(attrs["role_score"]),
            cluster_id=int(attrs["cluster_id"]), priority_score=float(attrs["priority_score"]),
            evidence=attrs["evidence"], is_seed=bool(attrs["is_seed"]), depth=int(attrs["depth"]),
            in_kzt=float(attrs["in_kzt"]), out_kzt=float(attrs["out_kzt"]),
            in_deg=int(attrs["in_deg"]), out_deg=int(attrs["out_deg"]),
        ))
    graph_edges = [
        dict(source=int(u), target=int(v), sum_kzt=float(d["sum_kzt"]), n_tx=int(d["n_tx"]))
        for u, v, d in G.edges(data=True)
    ]
    with open(out_dir / "graph_export.json", "w", encoding="utf-8") as f:
        json.dump(dict(nodes=graph_nodes, edges=graph_edges), f, ensure_ascii=False)

    print(f"\nВыгрузки записаны в {out_dir}/:")
    print(f"  nodes_roles.csv   : {len(nodes_roles)} строк")
    print(f"  clusters.csv      : {len(clusters)} строк")
    print(f"  top_nodes.csv     : {len(top_nodes)} строк")
    print(f"  graph_export.json : {len(graph_nodes)} узлов, {len(graph_edges)} рёбер")


def write_analysis_notes(df: pd.DataFrame, G: nx.DiGraph, out_dir: Path) -> None:
    lines = ["# Дополнительные наблюдения (авто-сгенерировано pipeline.py)\n"]

    lines.append("## Устойчивость сети (что если изъять топ-N приоритетных узлов)\n")
    for topn in (10, 20, 30):
        remove = set(df.sort_values("priority_score", ascending=False).head(topn).gid)
        H = G.copy()
        H.remove_nodes_from(remove & set(H.nodes()))
        comps = list(nx.weakly_connected_components(H)) if H.number_of_nodes() else []
        giant = max((len(c) for c in comps), default=0)
        lines.append(
            f"- Изъятие топ-{topn}: {H.number_of_nodes()} узлов остаётся, "
            f"{len(comps)} компонент связности, крупнейшая — {giant} узлов "
            f"(было {nx.number_weakly_connected_components(G)} компонент / "
            f"{max((len(c) for c in nx.weakly_connected_components(G)), default=0)} в крупнейшей)."
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

    lines.append("\n## Полнота данных / что запросить дальше\n")
    lines.append(
        "- 19 из 81 seed отсутствуют в edges (нет ни одного перевода в выборке) — "
        "стоит запросить их движения по счёту вне периода/банка."
    )
    lines.append(
        "- Обрыв на 4-м колене у 444 узлов — для узлов с высоким in_deg среди них "
        "(классифицированы как consolidator с пониженным role_score) стоит запросить "
        "исходящие переводы на 5-м колене."
    )
    lines.append(
        "- Транзакции < 5 000 KZT не в выборке — возможное дробление сумм ниже порога "
        "не видно; стоит запросить сырые транзакции без порога для топ-приоритетных gid."
    )

    with open(out_dir / "analysis_notes.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  analysis_notes.md : доп. наблюдения для демо")


# =================================================================== main ===

def run(data_dir: Path, out_dir: Path, build_viewer: bool = True) -> pd.DataFrame:
    t_start = time.time()
    edges, nodes, tx = load(data_dir)
    sanity_check(edges, nodes, tx)

    G = build_graph(edges)
    df = structural_features(G, nodes)

    temp = temporal_features(tx, df.gid)
    df = df.merge(temp, on="gid", how="left")

    df["cluster_id"] = cluster_nodes(G, df).values

    df = assign_roles(df)
    df = compute_priority(df)

    clusters = build_clusters_table(df, edges)
    top_nodes = build_top_nodes(df, n=40)

    write_outputs(df, clusters, top_nodes, G, out_dir)
    write_analysis_notes(df, G, out_dir)

    elapsed = time.time() - t_start
    print(f"\nПолный пересчёт занял {elapsed:.1f} сек (лимит 5 мин).")

    if build_viewer:
        try:
            from build_viewer import build as build_viewer_html
        except ImportError:
            import sys
            sys.path.insert(0, str(Path(__file__).parent))
            from build_viewer import build as build_viewer_html
        build_viewer_html(df, edges, clusters, out_dir)

    print("\nПроверка ролей (распределение):")
    print(df.role.value_counts().to_string())
    return df


def main():
    ap = argparse.ArgumentParser(description="Граф денег — пайплайн ролей/кластеров/приоритетов")
    ap.add_argument("--data", default="data", help="папка с parquet-файлами")
    ap.add_argument("--out", default="out", help="куда писать выгрузки")
    ap.add_argument("--no-viewer", action="store_true", help="не собирать graph.html")
    a = ap.parse_args()
    run(Path(a.data), Path(a.out), build_viewer=not a.no_viewer)


if __name__ == "__main__":
    main()
