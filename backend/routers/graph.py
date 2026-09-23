"""GET /api/summary — агрегаты для Overview; GET /api/graph — данные для Network."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

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
    gid: int | None = Query(default=None, description="центр окрестности"),
    depth: int = Query(default=1, ge=1, le=3, description="радиус окрестности в рёбрах (с gid)"),
    limit: int = Query(default=DEFAULT_GRAPH_LIMIT, ge=1, le=20000),
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
        keep_ids = _neighborhood(all_edges, gid, depth)
    else:
        keep_ids = {n["id"] for n in all_nodes}
        if role:
            keep_ids &= {n["id"] for n in all_nodes if n["role"] == role}
        if cluster_id is not None:
            keep_ids &= {n["id"] for n in all_nodes if n["cluster_id"] == cluster_id}

    truncated = False
    if len(keep_ids) > limit:
        ranked = sorted(keep_ids, key=lambda i: by_id.get(i, {}).get("priority_score", 0), reverse=True)
        keep_ids = set(ranked[:limit])
        truncated = True

    # id/source/target -> str: исходные gid — 18-значные числа, выше
    # Number.MAX_SAFE_INTEGER в JS, JSON-число потеряло бы точность в браузере.
    nodes_out = [GraphNode(**{**n, "id": str(n["id"])}) for n in all_nodes if n["id"] in keep_ids]
    edges_out = [
        GraphEdge(**{**e, "source": str(e["source"]), "target": str(e["target"])})
        for e in all_edges if e["source"] in keep_ids and e["target"] in keep_ids
    ]
    return GraphResponse(nodes=nodes_out, edges=edges_out, truncated=truncated)


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
