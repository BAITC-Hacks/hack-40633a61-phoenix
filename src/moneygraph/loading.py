"""Загрузка исходных parquet-файлов и проверка их консистентности."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


class DataLoadError(RuntimeError):
    """Понятная ошибка вместо трейсбека, когда входных данных нет/они битые."""


@dataclass(frozen=True)
class RawData:
    """Три сырых датафрейма, с которых начинается пайплайн."""

    edges: pd.DataFrame
    nodes: pd.DataFrame
    tx: pd.DataFrame


REQUIRED_FILES = ("edges.parquet", "nodes.parquet", "transactions.parquet")


def load(data_dir: Path) -> RawData:
    """Читает edges/nodes/transactions.parquet из ``data_dir``.

    Raises:
        DataLoadError: если папки/файлов нет или их нельзя прочитать —
            с понятным сообщением, что именно отсутствует и что делать.
    """
    if not data_dir.exists():
        raise DataLoadError(
            f"Папка с данными не найдена: {data_dir}. "
            f"Ожидались файлы {', '.join(REQUIRED_FILES)}."
        )

    missing = [name for name in REQUIRED_FILES if not (data_dir / name).exists()]
    if missing:
        raise DataLoadError(
            f"В {data_dir} не хватает файлов: {', '.join(missing)}. "
            f"Положите исходные .parquet в data/ и запустите ./run.sh заново."
        )

    try:
        edges = pd.read_parquet(data_dir / "edges.parquet")
        nodes = pd.read_parquet(data_dir / "nodes.parquet")
        tx = pd.read_parquet(data_dir / "transactions.parquet")
    except Exception as exc:  # noqa: BLE001 — сознательно оборачиваем любую ошибку чтения
        raise DataLoadError(f"Не удалось прочитать parquet из {data_dir}: {exc}") from exc

    tx = tx.copy()
    tx["date"] = pd.to_datetime(tx["date"])
    return RawData(edges=edges, nodes=nodes, tx=tx)


def sanity_check(raw: RawData) -> None:
    """Печатает сводку по данным и падает с AssertionError, если edges/tx
    не сходятся по парам (src, dst) — жёсткая проверка консистентности."""
    edges, nodes, tx = raw.edges, raw.nodes, raw.tx

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
    print(
        f"  узлов без единого ребра: {len(orphans)} (из них seed: "
        f"{len(orphans & set(nodes[nodes.is_seed].gid))})"
    )
    print("=" * 70)
