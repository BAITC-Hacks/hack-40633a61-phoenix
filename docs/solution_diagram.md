# Схема решения

```mermaid
flowchart LR
    subgraph INPUT["Строгий вход"]
        N["nodes.parquet\nID и атрибуты"]
        E["edges.parquet\nструктурные связи"]
        T["transactions.parquet\nфактические переводы + tx_id"]
        V["Schema/type/date validation\nunknown ID → reject"]
        N --> V
        E --> V
        T --> V
    end

    subgraph NORMALIZE["Изолированный active run"]
        I["Сохранение исходных ID\nи дополнительных полей"]
        U["Агрегация transaction-пар\n+ union edge-only пар"]
        V --> I --> U
    end

    subgraph ANALYTICS["Объяснимая аналитика"]
        G["Направленный граф\nsum_kzt + n_tx"]
        M["Структурные и временные метрики\nциклы · pass-through · bursts"]
        C["Louvain-кластеры"]
        R["AML risk 0–100\nузел · связь · транзакция · кластер"]
        U --> G --> M
        G --> C
        M --> R
        C --> R
    end

    subgraph API["FastAPI — только analysis_id"]
        A["summary / graph / nodes\nclusters / top / AI"]
        D["DELETE analysis\nочистка run + cache"]
        R --> A
    end

    subgraph UI["RU/KK рабочее пространство"]
        W["Upload → force graph → node card"]
        L["Риск-цвет/размер/толщина\nпоиск · highlight · fit/reset"]
        B["Большая сеть:\ncluster overview → раскрытие"]
        X["Backend-only OpenAI\nограниченный active context"]
        A --> W
        W --> L
        W --> B
        A --> X
        D --> W
    end
```

`transactions.parquet` является источником фактических переводов. Исходные
ID и детали операций сохраняются, неизвестные ID не подменяются техническими
или демонстрационными узлами. Все risk-формулировки — AML-гипотезы для проверки.
