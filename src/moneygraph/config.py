"""Все пороги, веса и цветовые константы пайплайна — в одном месте.

Ничего в остальных модулях не должно содержать «магических чисел»: если
понадобится объяснить жюри, откуда взялся порог, весь ответ — здесь и в
README (раздел «Критерии ролей»).
"""

from __future__ import annotations

#: Список ролей в порядке проверки правил (см. ``roles.assign_roles``).
ROLES: list[str] = [
    "coordinator",
    "consolidator",
    "distributor",
    "transit",
    "terminal",
    "peripheral",
]

#: Пороги признаков -> роль. Обоснование каждого — в README ("Критерии ролей").
TH: dict[str, float] = dict(
    CONSOLIDATOR_IN_DEG=8,   # 90-й+ перцентиль in_deg среди узлов с in_deg>0 (17 узлов, диапазон 8-24)
    DISTRIBUTOR_OUT_DEG=10,  # верхние ~9% узлов с исходящими (64 узла, до 116 получателей)
    COORDINATOR_IN_DEG=8,    # = CONSOLIDATOR_IN_DEG
    COORDINATOR_OUT_DEG=10,  # = DISTRIBUTOR_OUT_DEG -> пересечение даёт 9 узлов-кандидатов
    TRANSIT_PASS_LOW=0.8,    # окно pass_through, где деньги "проходят, не оседая"
    TRANSIT_PASS_HIGH=1.2,
    FAST_TRANSIT_DAYS=2,     # медианная задержка приём->отправка <= N дней => "быстрый транзит"
    BURST_PAYERS=3,          # 3+ разных плательщика в один день => синхронный платёж (evidence бонус)
    CYCLE_LENGTH_BOUND=6,
    MIN_CLUSTER_STABLE=5,    # кластер с 5+ узлами считаем "устойчивым" при интерпретации
)

#: Вес роли в priority_score (см. ``priority.compute_priority``).
ROLE_WEIGHT: dict[str, float] = {
    "coordinator": 1.00,
    "consolidator": 0.85,
    "distributor": 0.75,
    "transit": 0.40,
    "terminal": 0.30,
    "peripheral": 0.10,
}

#: Веса компонентов priority_score (должны суммироваться в 1.0).
PRIORITY_WEIGHTS: dict[str, float] = dict(
    role=0.35,
    pagerank=0.25,
    volume=0.20,
    betweenness=0.15,
    novelty=0.05,
)

#: Цвет узла по роли — используется и в offline graph.html, и в веб-дашборде
#: (frontend/js/svg-icons.js держит те же значения, чтобы легенда совпадала).
ROLE_COLOR: dict[str, str] = {
    "coordinator": "#e63946",
    "consolidator": "#f4a261",
    "distributor": "#9b5de5",
    "transit": "#4895ef",
    "terminal": "#2a9d8f",
    "peripheral": "#adb5bd",
}

#: Человекочитаемые названия ролей (RU) — офлайн-вьювер и analysis_notes.
ROLE_LABEL_RU: dict[str, str] = {
    "coordinator": "координатор",
    "consolidator": "консолидатор",
    "distributor": "распределитель",
    "transit": "транзит",
    "terminal": "конечный получатель",
    "peripheral": "периферия",
}

#: Названия колонок обязательных выгрузок (используется в exports.py и тестах).
NODES_ROLES_REQUIRED_COLUMNS: list[str] = [
    "gid", "role", "role_score", "cluster_id", "priority_score", "evidence",
]
