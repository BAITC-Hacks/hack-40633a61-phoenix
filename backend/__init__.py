"""FastAPI backend дашборда «Граф денег».

Backend не пересчитывает аналитику — он читает уже готовые выгрузки
пайплайна (``out/nodes_roles.csv``, ``out/clusters.csv``, ``out/top_nodes.csv``,
``out/graph_export.json``), которые генерирует ``src/moneygraph`` (см.
``run.sh``). Это единственное место, где эти файлы читаются в рантайме
сервера — см. :mod:`backend.data_store`.
"""
