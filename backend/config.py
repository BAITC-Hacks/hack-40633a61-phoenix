"""Настройки backend: пути к данным и переменные окружения AI-ассистента.

Все значения читаются из окружения (и ``.env`` в корне репозитория, см.
``.env.example``), с разумными значениями по умолчанию — сервер обязан
подниматься и работать полностью без AI_API_KEY (LLM — опциональная фича).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

#: Корень репозитория (на уровень выше backend/).
REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    """Иммутабельные настройки процесса, посчитанные один раз при старте."""

    repo_root: Path
    out_dir: Path
    data_dir: Path
    frontend_dir: Path
    runs_dir: Path
    cors_origins: list[str]

    ai_api_key: str | None
    ai_api_base_url: str
    ai_model: str
    ai_request_timeout_s: float


@lru_cache
def get_settings() -> Settings:
    """Кэшированные настройки. ``.env`` читается один раз при первом вызове."""
    load_dotenv(REPO_ROOT / ".env")

    out_dir = Path(os.environ.get("MONEYGRAPH_OUT_DIR", str(REPO_ROOT / "out")))
    data_dir = Path(os.environ.get("MONEYGRAPH_DATA_DIR", str(REPO_ROOT / "data")))
    # Production bundle built by Vite. Development uses Vite's /api proxy.
    frontend_dir = Path(os.environ.get("MONEYGRAPH_FRONTEND_DIR", str(REPO_ROOT / "frontend" / "dist")))

    cors_raw = os.environ.get("CORS_ORIGINS", "*")
    cors_origins = [o.strip() for o in cors_raw.split(",") if o.strip()]

    ai_api_key = (os.environ.get("OPENAI_API_KEY") or os.environ.get("AI_API_KEY", "")).strip() or None
    ai_api_base_url = (
        os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("AI_API_BASE_URL")
        or "https://api.openai.com/v1"
    ).rstrip("/")
    ai_model = os.environ.get("OPENAI_MODEL") or os.environ.get("AI_MODEL", "gpt-4o-mini")
    ai_timeout = float(os.environ.get("AI_REQUEST_TIMEOUT_S", "30"))

    return Settings(
        repo_root=REPO_ROOT,
        out_dir=out_dir,
        data_dir=data_dir,
        frontend_dir=frontend_dir,
        runs_dir=Path(os.environ.get("MONEYGRAPH_RUNS_DIR", str(REPO_ROOT / "runs"))),
        cors_origins=cors_origins,
        ai_api_key=ai_api_key,
        ai_api_base_url=ai_api_base_url,
        ai_model=ai_model,
        ai_request_timeout_s=ai_timeout,
    )
