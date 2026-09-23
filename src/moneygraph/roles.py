"""Присвоение роли каждому узлу по явным, документированным правилам.

Порядок проверки — сверху вниз (coordinator первым, peripheral — остаток).
Это не ML-модель, а прозрачное дерево решений: для любого gid можно за
секунды показать, какая ветка сработала и почему (см. README, раздел
«Критерии ролей»).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import TH


def _sigmoid_conf(x: float, k: float = 0.15, mid: float = 0.0) -> float:
    return float(1 / (1 + np.exp(-k * (x - mid))))


def assign_roles(df: pd.DataFrame) -> pd.DataFrame:
    """Добавляет колонки ``role``, ``role_score``, ``evidence`` к ``df``."""
    df = df.copy()
    role = pd.Series("peripheral", index=df.index, dtype=object)
    role_score = pd.Series(0.3, index=df.index, dtype=float)
    evidence = pd.Series("", index=df.index, dtype=object)

    for i, r in df.iterrows():
        seed_note = " (seed: входящие занижены — граф собран от него)" if r.is_seed else ""
        is_coord = r.in_deg >= TH["COORDINATOR_IN_DEG"] and r.out_deg >= TH["COORDINATOR_OUT_DEG"]
        is_consol = r.in_deg >= TH["CONSOLIDATOR_IN_DEG"]
        is_distrib = r.out_deg >= TH["DISTRIBUTOR_OUT_DEG"]
        is_transit = (
            r.in_deg >= 1 and r.out_deg >= 1
            and pd.notna(r.pass_through)
            and TH["TRANSIT_PASS_LOW"] <= r.pass_through <= TH["TRANSIT_PASS_HIGH"]
        )

        if r.in_deg == 0 and r.out_deg == 0:
            role.at[i] = "peripheral"
            role_score.at[i] = 0.2
            evidence.at[i] = (
                "Seed-клиент без единого ребра в выборке — 0 входящих и исходящих переводов "
                "(порог 5 000 KZT или операции вне банка)."
            )
            continue

        if is_coord:
            role.at[i] = "coordinator"
            role_score.at[i] = round(min(0.95, _sigmoid_conf(r.in_deg + r.out_deg, k=0.08, mid=25)), 2)
            evidence.at[i] = (
                f"Одновременно принимает от {r.in_deg} плательщиков ({r.in_kzt:,.0f} KZT) и "
                f"рассылает {r.out_deg} получателям ({r.out_kzt:,.0f} KZT) — двусторонний хаб, "
                f"кандидат в организаторы.{seed_note}"
            )[:200]
        elif is_consol:
            role.at[i] = "consolidator"
            if r.truncated_by_depth:
                role_score.at[i] = round(min(0.65, _sigmoid_conf(r.in_deg, k=0.2, mid=10)), 2)
                evidence.at[i] = (
                    f"На 4-м колене получает от {r.in_deg} плательщиков ({r.in_kzt:,.0f} KZT); "
                    f"исходящие переводы за пределами выборки не видны — вероятная точка "
                    f"консолидации, не подтверждено."
                )[:200]
            else:
                role_score.at[i] = round(min(0.95, _sigmoid_conf(r.in_deg, k=0.15, mid=12)), 2)
                pt_txt = f", уходит дальше {r.pass_through*100:.0f}%" if pd.notna(r.pass_through) else ""
                evidence.at[i] = (
                    f"Получает от {r.in_deg} разных плательщиков ({r.in_kzt:,.0f} KZT){pt_txt} — "
                    f"точка накопления средств.{seed_note}"
                )[:200]
        elif is_distrib:
            role.at[i] = "distributor"
            role_score.at[i] = round(min(0.95, _sigmoid_conf(r.out_deg, k=0.08, mid=20)), 2)
            evidence.at[i] = (
                f"Рассылает {r.out_deg} получателям ({r.out_kzt:,.0f} KZT), получая лишь от "
                f"{r.in_deg} плательщиков — веерное распределение средств вниз по цепочке.{seed_note}"
            )[:200]
        elif is_transit:
            role.at[i] = "transit"
            closeness = 1 - min(abs(r.pass_through - 1.0) / 0.2, 1.0)
            role_score.at[i] = round(0.5 + 0.4 * closeness, 2)
            lag_txt = ""
            if pd.notna(r.get("median_lag_days", np.nan)):
                lag_txt = f", медианная задержка {r.median_lag_days:.0f} дн."
            evidence.at[i] = (
                f"Пропускает средства не удерживая: получил {r.in_kzt:,.0f} KZT, отдал "
                f"{r.out_kzt:,.0f} KZT ({r.pass_through:.2f}x) от {r.in_deg} плательщиков "
                f"{r.out_deg} получателям{lag_txt}.{seed_note}"
            )[:200]
        elif r.out_deg == 0:
            role.at[i] = "terminal"
            if r.truncated_by_depth:
                role_score.at[i] = round(min(0.55, 0.3 + 0.03 * r.in_deg), 2)
                evidence.at[i] = (
                    f"Обрыв обхода на 4-м колене: исходящие за пределами выборки не видны. "
                    f"Получил {r.in_kzt:,.0f} KZT от {r.in_deg} плательщиков — возможный, но "
                    f"не подтверждённый конечный получатель."
                )[:200]
            else:
                role_score.at[i] = round(min(0.95, 0.7 + 0.02 * r.in_deg), 2)
                evidence.at[i] = (
                    f"Нет исходящих переводов на {int(r.depth)}-м колене (обход не был "
                    f"искусственно прерван, глубина < 4) — получил {r.in_kzt:,.0f} KZT от "
                    f"{r.in_deg} плательщиков и удержал их."
                )[:200]
        else:
            role.at[i] = "peripheral"
            pt_txt = f", pass_through={r.pass_through:.2f}" if pd.notna(r.pass_through) else ""
            role_score.at[i] = round(0.3 + 0.05 * min(r.in_deg + r.out_deg, 4), 2)
            evidence.at[i] = (
                f"Низкая активность в выборке: {r.in_deg} вход. / {r.out_deg} исход., "
                f"{(r.in_kzt + r.out_kzt):,.0f} KZT суммарно{pt_txt} — выраженных признаков "
                f"роли не выявлено."
            )[:200]

    df["role"] = role
    df["role_score"] = role_score
    df["evidence"] = evidence
    return df
