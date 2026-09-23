"""moneygraph — аналитический пайплайн кейса «Граф денег» (HackAlem AI).

Пакет разбит на модули с единственной ответственностью каждый:

- :mod:`moneygraph.config`     — все пороги, веса, цвета ролей в одном месте.
- :mod:`moneygraph.loading`    — чтение parquet + проверка консистентности.
- :mod:`moneygraph.graph`      — сборка направленного графа NetworkX.
- :mod:`moneygraph.features`   — структурные признаки узлов.
- :mod:`moneygraph.temporal`   — временные признаки из transactions.parquet.
- :mod:`moneygraph.clustering` — Louvain-кластеризация + таблица кластеров.
- :mod:`moneygraph.roles`      — присвоение ролей по явным правилам.
- :mod:`moneygraph.priority`   — priority_score и топ узлов.
- :mod:`moneygraph.exports`    — запись CSV/JSON/analysis_notes.md.
- :mod:`moneygraph.viewer`     — офлайн-визуализация out/graph.html (pyvis).
- :mod:`moneygraph.pipeline`   — оркестратор, вызывающий шаги по порядку.
- :mod:`moneygraph.cli`        — точка входа командной строки.

Backend (FastAPI) не импортирует эти модули для пересчёта — он читает уже
готовые выгрузки из ``out/`` (см. ``backend/config.py``), поэтому логика
существует в единственном месте и не дублируется.
"""

from __future__ import annotations

__version__ = "2.0.0"

__all__ = ["__version__"]
