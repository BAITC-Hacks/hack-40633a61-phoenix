#!/usr/bin/env bash
# Единая команда воспроизводимости: сырые .parquet -> nodes_roles.csv,
# clusters.csv, top_nodes.csv, graph_export.json, graph.html (< 5 минут).
#
# Использование:
#   ./run.sh                # data/ -> out/
#   ./run.sh path/to/data path/to/out
set -euo pipefail
cd "$(dirname "$0")"

DATA_DIR="${1:-data}"
OUT_DIR="${2:-out}"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt

PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}" python3 -m moneygraph.cli --data "$DATA_DIR" --out "$OUT_DIR"

echo ""
echo "Готово. Варианты просмотра результата:"
echo "  1) Офлайн-схема без сервера: откройте $OUT_DIR/graph.html в браузере (двойной клик, интернет не нужен)."
echo "  2) Полный дашборд с AI-ассистентом: ./run_server.sh, затем http://localhost:8000"
