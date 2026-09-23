"""Pydantic-схемы ответов API — контракт между backend и frontend."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RoleCount(BaseModel):
    role: str
    count: int


class Summary(BaseModel):
    """Агрегаты для карточки «Latest analysis» на Overview."""

    n_nodes: int
    n_edges: int
    n_seed: int
    n_components: int
    n_clusters: int
    n_high_priority: int = Field(description="узлов с priority_score >= high_priority_threshold")
    high_priority_threshold: float
    role_counts: list[RoleCount]
    generated_at: datetime
    status: str = "completed"


class NodeListItem(BaseModel):
    # gid как str: исходные id — 18-значные числа (~1e17), выше
    # Number.MAX_SAFE_INTEGER в JS (2^53-1, ~9e15) — JSON-число потеряло бы
    # точность при парсинге в браузере (разные gid могли бы схлопнуться в
    # один и тот же округлённый float). Строка — единственный безопасный
    # способ передать такой id в JSON фронтенду без искажений.
    gid: str
    role: str
    role_score: float
    cluster_id: int
    priority_score: float
    is_seed: bool
    in_deg: int
    out_deg: int
    in_kzt: float
    out_kzt: float


class NodeListResponse(BaseModel):
    items: list[NodeListItem]
    total: int
    page: int
    page_size: int


class NeighborEdge(BaseModel):
    gid: str  # см. комментарий у NodeListItem.gid — точность int64 в JSON
    role: str
    sum_kzt: float
    n_tx: int
    direction: str  # "in" | "out"


class NodeDetail(BaseModel):
    gid: str  # см. комментарий у NodeListItem.gid — точность int64 в JSON
    role: str
    role_score: float
    cluster_id: int
    priority_score: float
    evidence: str
    is_seed: bool
    depth: int
    in_deg: int
    out_deg: int
    in_kzt: float
    out_kzt: float
    in_tx: int | None = None
    out_tx: int | None = None
    pagerank: float | None = None
    betweenness: float | None = None
    pass_through: float | None = None
    truncated_by_depth: bool | None = None
    in_cycle: bool | None = None
    median_lag_days: float | None = None
    max_same_day_payers: int | None = None
    fast_transit: bool | None = None
    synchronized_burst: bool | None = None
    neighbors: list[NeighborEdge] = Field(default_factory=list)


class ClusterOut(BaseModel):
    cluster_id: int
    n_nodes: int
    n_seed: int
    sum_kzt_internal: float
    top_gids: list[str]  # см. комментарий у NodeListItem.gid — точность int64 в JSON
    hypothesis: str


class TopNodeOut(BaseModel):
    rank: int
    gid: str  # см. комментарий у NodeListItem.gid — точность int64 в JSON
    role: str
    priority_score: float
    why: str


class GraphNode(BaseModel):
    id: str  # см. комментарий у NodeListItem.gid — точность int64 в JSON
    role: str
    role_score: float
    cluster_id: int
    priority_score: float
    is_seed: bool
    depth: int
    in_deg: int
    out_deg: int
    in_kzt: float
    out_kzt: float


class GraphEdge(BaseModel):
    source: str  # см. комментарий у NodeListItem.gid — точность int64 в JSON
    target: str
    sum_kzt: float
    n_tx: int


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool = Field(description="True, если выдача обрезана лимитом")


class AIAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class AICitation(BaseModel):
    gid: str  # см. комментарий у NodeListItem.gid — точность int64 в JSON
    role: str
    priority_score: float


class AIAskResponse(BaseModel):
    answer: str
    citations: list[AICitation] = Field(default_factory=list)
    model: str


class ErrorResponse(BaseModel):
    detail: str
    extra: dict[str, Any] | None = None
