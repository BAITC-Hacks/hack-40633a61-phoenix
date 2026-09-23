# Схема решения

Один слайд: данные → метрики → роли → интерфейс.

```mermaid
flowchart LR
    subgraph IN["Вход (data/*.parquet)"]
        E["edges.parquet\nsrc→dst, sum_kzt, n_tx, depth"]
        N["nodes.parquet\ngid, depth, is_seed"]
        T["transactions.parquet\nsrc, dst, date, sum_kzt"]
    end

    subgraph GRAPH["Граф (NetworkX DiGraph)"]
        G["2 248 узлов, 3 119 рёбер\nнаправленный, взвешенный по sum_kzt"]
    end

    subgraph METRICS["Метрики (src/pipeline.py)"]
        M1["Структурные:\nin/out_deg, in/out_kzt,\npagerank, betweenness,\npass_through, циклы,\ncomponent_id"]
        M2["Временные (transactions):\nмедианная задержка\nприём→отправка,\nсинхронные платежи/день"]
        M3["Кластеры:\nLouvain на неориентированной\nпроекции (67 сообществ)"]
    end

    subgraph ROLES["Роли (явные правила с порогами)"]
        R1["coordinator\nin_deg≥8 И out_deg≥10"]
        R2["consolidator\nin_deg≥8"]
        R3["distributor\nout_deg≥10"]
        R4["transit\npass_through∈[0.8,1.2]"]
        R5["terminal\nout_deg=0"]
        R6["peripheral\nостальное"]
    end

    subgraph PRIORITY["Приоритет"]
        P["priority_score =\n0.35·role_weight + 0.25·pagerank_pct\n+ 0.20·volume_pct + 0.15·betweenness_pct\n+ 0.05·novelty(¬seed)"]
    end

    subgraph OUT["Выход"]
        O1["nodes_roles.csv (2 248 строк)"]
        O2["clusters.csv (68 кластеров)"]
        O3["top_nodes.csv (40 строк)"]
        O4["graph.html — офлайн-схема:\nроли/кластеры, поиск по gid,\nкарточка узла"]
    end

    E --> G
    N --> G
    T --> M2
    G --> M1
    G --> M3
    M1 --> ROLES
    ROLES --> P
    M1 --> P
    P --> OUT
    M3 --> O2
    ROLES --> O1
    P --> O3
    O1 --> O4
    O2 --> O4
```

**Аналитик:** получает `data/*.parquet` → запускает `./run.sh` → за секунды получает
`out/nodes_roles.csv`, `out/clusters.csv`, `out/top_nodes.csv` и открывает
`out/graph.html`, где ищет любой из 2 248 gid, видит его роль, кластер и
обоснование, и формирует список на углублённую проверку.
