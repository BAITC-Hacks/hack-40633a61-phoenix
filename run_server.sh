#!/usr/bin/env bash
# Поднимает backend (FastAPI/uvicorn) и отдаёт frontend — одна команда.
#
# Использование:
#   ./run_server.sh              # http://localhost:8000
#   PORT=8080 ./run_server.sh    # другой порт
#
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt

echo "Собираю frontend…"
(cd frontend && npm ci --silent && npm run build)

echo ""
echo "Дашборд: http://${HOST}:${PORT}"
echo "Health:  http://${HOST}:${PORT}/api/health"
echo ""

exec uvicorn backend.app:app --host "$HOST" --port "$PORT"
