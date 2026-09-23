#!/usr/bin/env bash
# Единая команда воспроизводимости: сырые .parquet -> nodes_roles.csv,
# clusters.csv, top_nodes.csv, graph.html (< 5 минут).
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

python3 src/pipeline.py --data "$DATA_DIR" --out "$OUT_DIR"

echo ""
echo "Готово. Откройте $OUT_DIR/graph.html в браузере (двойной клик, интернет не нужен)."
