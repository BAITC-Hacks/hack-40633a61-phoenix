"""Временные признаки из transactions.parquet."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import TH


def temporal_features(tx: pd.DataFrame, gids: pd.Series) -> pd.DataFrame:
    """Задержка приём->отправка и синхронность входящих платежей за день.

    - ``median_lag_days`` — медианное число дней между получением платежа и
      следующей исходящей отправкой того же узла (None, если нет обеих сторон).
    - ``max_same_day_payers`` — максимум разных плательщиков в один день.
    - ``fast_transit`` / ``synchronized_burst`` — булевы флаги по порогам ``TH``.
    """
    tx = tx.copy()
    in_by_node = tx.groupby("dst")["date"].apply(lambda s: sorted(s.tolist()))
    out_by_node = tx.groupby("src")["date"].apply(lambda s: sorted(s.tolist()))
    burst_by_node = tx.groupby(["dst", "date"])["src"].nunique().groupby("dst").max()

    lag_days: dict[int, float] = {}
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
