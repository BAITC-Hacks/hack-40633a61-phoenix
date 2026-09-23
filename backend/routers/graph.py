"""GET /api/summary — агрегаты для Overview; GET /api/graph — данные для Network."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from ..data_store import Dataset
from ..deps import get_dataset
from ..schemas import GraphEdge, GraphNode, GraphResponse, RoleCount, Summary

router = APIRouter(tags=["graph"])

#: priority_score, начиная с которого узел считается «high-priority» на Overview.
#: ~2.5% узлов в предоставленном датасете (58 из 2248) — верхний хвост распределения.
HIGH_PRIORITY_THRESHOLD = 0.75

#: Сколько узлов отдавать в /api/graph по умолчанию (без фильтров) —
#: защита от перегрузки браузера при полном датасете большего размера.
DEFAULT_GRAPH_LIMIT = 4000
CLUSTER_OVERVIEW_THRESHOLD = 800


@router.get("/summary", response_model=Summary)
def get_summary(ds: Dataset = Depends(get_dataset)) -> Summary:
    nodes = ds.nodes
    role_counts = [
        RoleCount(role=role, count=int(count))
        for role, count in nodes.role.value_counts().items()
    ]
    n_seed = int(nodes.is_seed.sum())
    # component_id — служебное поле pipeline, в CSV не экспортируется явно,
    # поэтому для Overview считаем слабосвязные компоненты по рёбрам графа.
    n_components = _count_weak_components(ds)

    return Summary(
        n_nodes=len(nodes),
        n_edges=len(ds.graph["edges"]),
        n_seed=n_seed,
        n_components=n_components,
        n_clusters=int(ds.clusters.cluster_id.nunique()),
        n_high_priority=int((nodes.priority_score >= HIGH_PRIORITY_THRESHOLD).sum()),
        high_priority_threshold=HIGH_PRIORITY_THRESHOLD,
        role_counts=role_counts,
        generated_at=datetime.fromtimestamp(ds.generated_at, tz=timezone.utc),
    )


def _count_weak_components(ds: Dataset) -> int:
    """Число слабосвязных компонент по рёбрам graph_export.json (+ орфаны как отдельные)."""
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for e in ds.graph["edges"]:
        union(e["source"], e["target"])
    for n in ds.graph["nodes"]:
        parent.setdefault(n["id"], n["id"])

    roots = {find(gid) for gid in parent}
    return len(roots)


@router.get("/graph", response_model=GraphResponse)
def get_graph(
    ds: Dataset = Depends(get_dataset),
    role: str | None = Query(default=None, description="фильтр по роли"),
    cluster_id: int | None = Query(default=None, description="фильтр по кластеру"),
    gid: str | None = Query(default=None, description="центр окрестности"),
    depth: int = Query(default=1, ge=1, le=3, description="радиус окрестности в рёбрах (с gid)"),
    limit: int = Query(default=DEFAULT_GRAPH_LIMIT, ge=1, le=20000),
    view: str = Query(default="auto", pattern="^(auto|full|clusters)$"),
) -> GraphResponse:
    """Данные для Network-визуализации, с опциональными фильтрами.

    Без фильтров отдаёт весь граф (до ``limit`` узлов по priority_score) —
    для больших датасетов используйте ``role``/``cluster_id``/``gid``+``depth``,
    чтобы не перегружать браузер.
    """
    all_nodes = ds.graph["nodes"]
    all_edges = ds.graph["edges"]
    by_id = {n["id"]: n for n in all_nodes}

    if gid is not None:
        internal_gid = ds.internal_id(gid)
        if internal_gid is None:
            raise HTTPException(status_code=404, detail=f"ID {gid} не найден в активном анализе.")
        keep_ids = _neighborhood(all_edges, internal_gid, depth)
    else:
        keep_ids = {n["id"] for n in all_nodes}
        if role:
            keep_ids &= {n["id"] for n in all_nodes if n["role"] == role}
        if cluster_id is not None:
            keep_ids &= {n["id"] for n in all_nodes if n["cluster_id"] == cluster_id}

    if view == "clusters" or (
        view == "auto"
        and gid is None
        and cluster_id is None
        and role is None
        and len(keep_ids) > CLUSTER_OVERVIEW_THRESHOLD
    ):
        return _cluster_overview(ds)

    truncated = False
    if len(keep_ids) > limit:
        ranked = sorted(keep_ids, key=lambda i: by_id.get(i, {}).get("priority_score", 0), reverse=True)
        keep_ids = set(ranked[:limit])
        truncated = True

    # id/source/target -> str: исходные gid — 18-значные числа, выше
    # Number.MAX_SAFE_INTEGER в JS, JSON-число потеряло бы точность в браузере.
    raw_by_id = {int(row.gid): row._asdict() for row in ds.raw_nodes.itertuples()}
    nodes_out = []
    for node in all_nodes:
        if node["id"] not in keep_ids:
            continue
        raw = raw_by_id.get(int(node["id"]), {})
        label = next(
            (
                str(raw[key])
                for key in ("name", "title", "entity_name", "type", "entity_type")
                if key in raw and raw[key] is not None
            ),
            None,
        )
        nodes_out.append(
            GraphNode(
                **{
                    **node,
                    "id": ds.external_id(node["id"]),
                    "label": label,
                    "kind": "entity",
                }
            )
        )
    edges_out = [
        GraphEdge(
            **{
                **e,
                "id": f"{ds.external_id(e['source'])}:{ds.external_id(e['target'])}",
                "source": ds.external_id(e["source"]),
                "target": ds.external_id(e["target"]),
                "tx_ids": [str(value) for value in e.get("tx_ids", [])],
            }
        )
        for e in all_edges if e["source"] in keep_ids and e["target"] in keep_ids
    ]
    return GraphResponse(
        nodes=nodes_out,
        edges=edges_out,
        truncated=truncated,
        view="full",
        total_nodes=len(all_nodes),
        aggregated=False,
    )


def _cluster_overview(ds: Dataset) -> GraphResponse:
    grouped = ds.nodes.groupby("cluster_id")
    cluster_nodes: list[GraphNode] = []
    for row in ds.clusters.itertuples():
        group = grouped.get_group(int(row.cluster_id))
        cluster_nodes.append(
            GraphNode(
                id=f"cluster:{int(row.cluster_id)}",
                role="cluster",
                role_score=0,
                cluster_id=int(row.cluster_id),
                priority_score=float(group.priority_score.max()),
                is_seed=bool(row.n_seed),
                depth=0,
                in_deg=int(group.in_deg.sum()),
                out_deg=int(group.out_deg.sum()),
                in_kzt=float(group.in_kzt.sum()),
                out_kzt=float(group.out_kzt.sum()),
                in_tx=int(group.in_tx.sum()),
                out_tx=int(group.out_tx.sum()),
                risk_score=float(row.risk_score),
                risk_level=row.risk_level,
                risk_factors=row.risk_factors,
                risk_explanation=row.risk_explanation,
                kind="cluster",
                label=f"Кластер {int(row.cluster_id)}",
                member_count=int(row.n_nodes),
            )
        )

    cluster_by_gid = {
        int(row.gid): int(row.cluster_id)
        for row in ds.nodes[["gid", "cluster_id"]].itertuples(index=False)
    }
    aggregate: dict[tuple[int, int], dict] = {}
    for edge in ds.graph["edges"]:
        source_cluster = cluster_by_gid[int(edge["source"])]
        target_cluster = cluster_by_gid[int(edge["target"])]
        if source_cluster == target_cluster:
            continue
        key = (source_cluster, target_cluster)
        item = aggregate.setdefault(
            key,
            {"sum_kzt": 0.0, "n_tx": 0, "risk_score": 0.0, "count": 0},
        )
        item["sum_kzt"] += float(edge["sum_kzt"])
        item["n_tx"] += int(edge["n_tx"])
        item["risk_score"] = max(item["risk_score"], float(edge["risk_score"]))
        item["count"] += 1

    cluster_edges = [
        GraphEdge(
            id=f"cluster:{source}:cluster:{target}",
            source=f"cluster:{source}",
            target=f"cluster:{target}",
            sum_kzt=values["sum_kzt"],
            n_tx=values["n_tx"],
            has_transactions=values["n_tx"] > 0,
            risk_score=values["risk_score"],
            risk_level=_risk_level(values["risk_score"]),
            risk_factors=f"{values['count']} межкластерных связей",
            risk_explanation="Агрегированная AML-гипотеза для межкластерного потока.",
        )
        for (source, target), values in aggregate.items()
    ]
    return GraphResponse(
        nodes=cluster_nodes,
        edges=cluster_edges,
        truncated=False,
        view="clusters",
        total_nodes=len(ds.nodes),
        aggregated=True,
    )


def _risk_level(score: float) -> str:
    if score >= 75:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 25:
        return "medium"
    return "low"


def _neighborhood(edges: list[dict], center: int, depth: int) -> set[int]:
    frontier = {center}
    visited = {center}
    adjacency: dict[int, set[int]] = {}
    for e in edges:
        adjacency.setdefault(e["source"], set()).add(e["target"])
        adjacency.setdefault(e["target"], set()).add(e["source"])
    for _ in range(depth):
        nxt: set[int] = set()
        for n in frontier:
            nxt |= adjacency.get(n, set())
        frontier = nxt - visited
        visited |= nxt
        if not frontier:
            break
    return visited
