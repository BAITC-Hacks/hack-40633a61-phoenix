"""FastAPI-приложение дашборда «Граф денег».

Запуск (см. также ../run_server.sh):

    uvicorn backend.app:app --reload --port 8000

Backend отдаёт JSON API под ``/api/*`` и статику фронтенда под ``/`` —
одна команда поднимает и данные, и интерфейс. Все данные читаются из
``out/`` (см. ``backend/data_store.py``) — сервер не пересчитывает
аналитику самостоятельно (это делает ``./run.sh`` -> ``src/moneygraph``).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .data_store import get_store
from .routers import ai, clusters, graph, nodes, uploads

logger = logging.getLogger("moneygraph.backend")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

settings = get_settings()

app = FastAPI(
    title="Граф денег — API",
    description="AML-аналитика по кейсу HackAlem AI: роли, кластеры, приоритеты, AI-ассистент.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or ["*"],
    allow_credentials="*" not in settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(graph.router, prefix="/api")
app.include_router(nodes.router, prefix="/api")
app.include_router(clusters.router, prefix="/api")
app.include_router(ai.router, prefix="/api")
app.include_router(uploads.router, prefix="/api")


@app.get("/api/health")
def health() -> dict:
    """Быстрая проверка живости + подсказка, если out/ ещё не сгенерирован."""
    missing = get_store().missing_files()
    return {
        "status": "ok" if not missing else "outputs_missing",
        "missing_files": missing,
        "hint": None if not missing else "Сначала запустите ./run.sh, чтобы сгенерировать out/*.",
    }


@app.on_event("startup")
def on_startup() -> None:
    missing = get_store().missing_files()
    if missing:
        logger.warning(
            "Не найдены выгрузки пайплайна: %s (папка %s). "
            "API вернёт 503 до тех пор, пока вы не запустите ./run.sh.",
            ", ".join(missing), settings.out_dir,
        )
    else:
        logger.info("Выгрузки пайплайна найдены в %s — сервер готов.", settings.out_dir)

    if not settings.ai_api_key:
        logger.info(
            "OPENAI_API_KEY не задан — /api/ai/ask будет отвечать 503 "
            "('AI-ассистент не настроен'). Остальной дашборд работает без него."
        )


# Статика фронтенда — чистый HTML/CSS/vanilla JS без сборки (никакого
# React/Vite/npm), лежит прямо в frontend/ и отдаётся как есть. Монтируется
# последней, чтобы не перехватывать /api/*.
if (settings.frontend_dir / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(settings.frontend_dir), html=True), name="frontend")
else:
    logger.warning(
        "Файл фронтенда не найден: %s/index.html.", settings.frontend_dir,
    )

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def frontend_missing() -> str:
        return (
            "<html><body style='font-family:sans-serif;padding:2rem;"
            "background:#10171b;color:#d7e2e6'>"
            "<h1>Граф денег — API работает, но папка frontend/ пуста</h1>"
            f"<p>Ожидался <code>index.html</code> в <code>{settings.frontend_dir}</code>.</p>"
            "<p>API доступен прямо сейчас: <a style='color:#7fe6c4' href='/api/summary'>"
            "/api/summary</a>, <a style='color:#7fe6c4' href='/api/health'>/api/health</a>.</p>"
            "</body></html>"
        )
