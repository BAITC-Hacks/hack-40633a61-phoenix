"""GET /api/clusters, GET /api/top."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..data_store import Dataset
from ..deps import get_dataset
from ..schemas import ClusterOut, TopNodeOut

router = APIRouter(tags=["clusters"])


@router.get("/clusters", response_model=list[ClusterOut])
def list_clusters(ds: Dataset = Depends(get_dataset)) -> list[ClusterOut]:
    out = []
    for r in ds.clusters.itertuples():
        top_gids_raw = str(r.top_gids) if not _is_nan(r.top_gids) else ""
        top_gids = [g for g in top_gids_raw.split(";") if g]
        out.append(ClusterOut(
            cluster_id=int(r.cluster_id), n_nodes=int(r.n_nodes), n_seed=int(r.n_seed),
            sum_kzt_internal=float(r.sum_kzt_internal), top_gids=top_gids,
            hypothesis=r.hypothesis,
        ))
    return out


@router.get("/top", response_model=list[TopNodeOut])
def list_top_nodes(ds: Dataset = Depends(get_dataset)) -> list[TopNodeOut]:
    return [
        TopNodeOut(rank=int(r.rank), gid=str(r.gid), role=r.role,
                   priority_score=float(r.priority_score), why=r.why)
        for r in ds.top_nodes.itertuples()
    ]


def _is_nan(value) -> bool:
    return isinstance(value, float) and value != value
