"""GET /api/nodes — список с пагинацией/фильтрами; GET /api/nodes/{gid} — карточка."""

from __future__ import annotations

import math

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query

from ..data_store import Dataset
from ..deps import get_dataset
from ..schemas import NeighborEdge, NodeDetail, NodeListItem, NodeListResponse

router = APIRouter(prefix="/nodes", tags=["nodes"])


def _clean(value):
    """NaN/NaT -> None, numpy-скаляры -> обычные python-типы (для Pydantic/JSON)."""
    if isinstance(value, float) and math.isnan(value):
        return None
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


@router.get("", response_model=NodeListResponse)
def list_nodes(
    ds: Dataset = Depends(get_dataset),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    role: str | None = Query(default=None),
    cluster_id: int | None = Query(default=None),
    is_seed: bool | None = Query(default=None),
    q: str | None = Query(default=None, description="поиск по gid (подстрока)"),
    sort_by: str = Query(default="priority_score"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
) -> NodeListResponse:
    df = ds.nodes

    if role:
        df = df[df.role == role]
    if cluster_id is not None:
        df = df[df.cluster_id == cluster_id]
    if is_seed is not None:
        df = df[df.is_seed == is_seed]
    if q:
        df = df[df.gid.astype(str).str.contains(q.strip(), na=False)]

    if sort_by in df.columns:
        df = df.sort_values(sort_by, ascending=(sort_dir == "asc"))

    total = len(df)
    start = (page - 1) * page_size
    page_df = df.iloc[start: start + page_size]

    items = [
        NodeListItem(
            gid=str(r.gid), role=r.role, role_score=float(r.role_score),
            cluster_id=int(r.cluster_id), priority_score=float(r.priority_score),
            is_seed=bool(r.is_seed), in_deg=int(r.in_deg), out_deg=int(r.out_deg),
            in_kzt=float(r.in_kzt), out_kzt=float(r.out_kzt),
        )
        for r in page_df.itertuples()
    ]
    return NodeListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/{gid}", response_model=NodeDetail)
def get_node(gid: int, ds: Dataset = Depends(get_dataset)) -> NodeDetail:
    row = ds.nodes[ds.nodes.gid == gid]
    if row.empty:
        raise HTTPException(status_code=404, detail=f"gid {gid} не найден в nodes_roles.csv")
    r = row.iloc[0].to_dict()

    role_by_id = {n["id"]: n["role"] for n in ds.graph["nodes"]}
    neighbors: list[NeighborEdge] = []
    for e in ds.graph["edges"]:
        if e["source"] == gid:
            neighbors.append(NeighborEdge(
                gid=str(e["target"]), role=role_by_id.get(e["target"], "?"),
                sum_kzt=e["sum_kzt"], n_tx=e["n_tx"], direction="out",
            ))
        elif e["target"] == gid:
            neighbors.append(NeighborEdge(
                gid=str(e["source"]), role=role_by_id.get(e["source"], "?"),
                sum_kzt=e["sum_kzt"], n_tx=e["n_tx"], direction="in",
            ))
    neighbors.sort(key=lambda n: n.sum_kzt, reverse=True)

    return NodeDetail(
        gid=str(r["gid"]), role=r["role"], role_score=float(r["role_score"]),
        cluster_id=int(r["cluster_id"]), priority_score=float(r["priority_score"]),
        evidence=r.get("evidence", ""), is_seed=bool(r.get("is_seed", False)),
        depth=int(_clean(r.get("depth")) or 0),
        in_deg=int(r.get("in_deg", 0)), out_deg=int(r.get("out_deg", 0)),
        in_kzt=float(r.get("in_kzt", 0.0)), out_kzt=float(r.get("out_kzt", 0.0)),
        in_tx=_clean(r.get("in_tx")), out_tx=_clean(r.get("out_tx")),
        pagerank=_clean(r.get("pagerank")), betweenness=_clean(r.get("betweenness")),
        pass_through=_clean(r.get("pass_through")),
        truncated_by_depth=_clean(r.get("truncated_by_depth")),
        in_cycle=_clean(r.get("in_cycle")),
        median_lag_days=_clean(r.get("median_lag_days")),
        max_same_day_payers=_clean(r.get("max_same_day_payers")),
        fast_transit=_clean(r.get("fast_transit")),
        synchronized_burst=_clean(r.get("synchronized_burst")),
        neighbors=neighbors[:50],
    )
