"""priority_score — кого аналитику смотреть первым."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import PRIORITY_WEIGHTS, ROLE_WEIGHT
from .features import pct_rank


def compute_priority(df: pd.DataFrame) -> pd.DataFrame:
    """``priority_score = 0.35·role_weight + 0.25·pagerank_pct + 0.20·volume_pct
    + 0.15·betweenness_pct + 0.05·novelty(¬is_seed)`` — веса из ``config.PRIORITY_WEIGHTS``.
    """
    df = df.copy()
    role_w = df.role.map(ROLE_WEIGHT).fillna(0.1)
    pr_pct = pct_rank(df.pagerank)
    vol_pct = pct_rank(df.in_kzt + df.out_kzt)
    bw_pct = pct_rank(df.betweenness)
    # известные seed уже в поле зрения аналитика — небольшой бонус за "новизну"
    # смещает фокус на реальные точки консолидации, а не на уже известных курьеров
    novelty = np.where(df.is_seed, 0.0, 1.0)

    w = PRIORITY_WEIGHTS
    raw = (
        w["role"] * role_w
        + w["pagerank"] * pr_pct
        + w["volume"] * vol_pct
        + w["betweenness"] * bw_pct
        + w["novelty"] * novelty
    )
    df["priority_score"] = raw.clip(0, 1).round(4)
    return df


def build_top_nodes(df: pd.DataFrame, n: int = 40) -> pd.DataFrame:
    """Топ-``n`` узлов по ``priority_score`` с человекочитаемым ``why``."""
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
