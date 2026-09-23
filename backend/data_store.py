"""Единая точка чтения выгрузок пайплайна (``out/*.csv``, ``graph_export.json``).

Все роутеры и ``ai_assistant.py`` используют :func:`get_store` вместо того,
чтобы каждый читал файлы по-своему — так логика чтения/валидации существует
в одном месте (см. требование «не копипастить» между backend и pipeline).

Кэш инвалидируется по mtime файлов, поэтому повторный ``./run.sh`` без
перезапуска сервера подхватится автоматически при следующем запросе.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

import pandas as pd

from .config import get_settings

REQUIRED_OUT_FILES = ("nodes_roles.csv", "clusters.csv", "top_nodes.csv", "graph_export.json")


class OutputsNotReadyError(RuntimeError):
    """out/*.csv или graph_export.json ещё не сгенерированы pipeline'ом."""


@dataclass
class Dataset:
    """Снимок всех выгрузок пайплайна, закэшированный в памяти."""

    nodes: pd.DataFrame
    clusters: pd.DataFrame
    top_nodes: pd.DataFrame
    graph: dict[str, Any]
    analysis_notes: str
    generated_at: float
    out_dir: Path


class DataStore:
    """Потокобезопасный кэш выгрузок с автоинвалидацией по mtime."""

    def __init__(self, out_dir: Path, runs_dir: Path | None = None) -> None:
        self._out_dir = out_dir
        self._runs_dir = runs_dir
        self._lock = Lock()
        self._cache: dict[str, tuple[float, Dataset]] = {}

    def _resolve(self, analysis_id: str | None = None) -> Path:
        if analysis_id is None:
            return self._out_dir
        if not analysis_id.isalnum() or len(analysis_id) != 32 or self._runs_dir is None:
            raise OutputsNotReadyError(f"Анализ {analysis_id!r} не найден.")
        out_dir = self._runs_dir / analysis_id / "out"
        if not out_dir.is_dir():
            raise OutputsNotReadyError(f"Анализ {analysis_id!r} не найден или ещё не завершён.")
        return out_dir

    def missing_files(self, analysis_id: str | None = None) -> list[str]:
        """Список отсутствующих обязательных файлов (пусто, если всё на месте)."""
        out_dir = self._resolve(analysis_id)
        return [name for name in REQUIRED_OUT_FILES if not (out_dir / name).exists()]

    def _latest_mtime(self, out_dir: Path) -> float:
        return max((out_dir / name).stat().st_mtime for name in REQUIRED_OUT_FILES)

    def get(self, analysis_id: str | None = None) -> Dataset:
        """Возвращает актуальный :class:`Dataset`.

        Raises:
            OutputsNotReadyError: если каких-то файлов из ``out/`` нет —
                с понятным сообщением, что нужно сначала запустить ``./run.sh``.
        """
        out_dir = self._resolve(analysis_id)
        missing = self.missing_files(analysis_id)
        if missing:
            raise OutputsNotReadyError(
                "Не найдены выгрузки пайплайна: " + ", ".join(missing) +
                f" (ожидались в {out_dir}). Сначала запустите ./run.sh."
            )

        mtime = self._latest_mtime(out_dir)
        cache_id = analysis_id or "demo"
        with self._lock:
            cached = self._cache.get(cache_id)
            if cached is not None and cached[0] == mtime:
                return cached[1]

            nodes = pd.read_csv(out_dir / "nodes_roles.csv")
            clusters = pd.read_csv(out_dir / "clusters.csv")
            top_nodes = pd.read_csv(out_dir / "top_nodes.csv")
            with open(out_dir / "graph_export.json", encoding="utf-8") as f:
                graph = json.load(f)
            notes_path = out_dir / "analysis_notes.md"
            notes = notes_path.read_text(encoding="utf-8") if notes_path.exists() else ""

            dataset = Dataset(
                nodes=nodes, clusters=clusters, top_nodes=top_nodes,
                graph=graph, analysis_notes=notes, generated_at=mtime, out_dir=out_dir,
            )
            self._cache[cache_id] = (mtime, dataset)
            return dataset


_store: DataStore | None = None


def get_store() -> DataStore:
    """Синглтон :class:`DataStore` для текущего процесса backend."""
    global _store
    if _store is None:
        settings = get_settings()
        _store = DataStore(settings.out_dir, settings.runs_dir)
    return _store
