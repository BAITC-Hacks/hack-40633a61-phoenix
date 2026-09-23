"""Точка входа командной строки: ``python -m moneygraph.cli --data data --out out``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .loading import DataLoadError
from .pipeline import run


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Граф денег — пайплайн ролей/кластеров/приоритетов")
    ap.add_argument("--data", default="data", help="папка с parquet-файлами")
    ap.add_argument("--out", default="out", help="куда писать выгрузки")
    ap.add_argument("--no-viewer", action="store_true", help="не собирать graph.html")
    args = ap.parse_args(argv)

    try:
        run(Path(args.data), Path(args.out), build_viewer=not args.no_viewer)
    except DataLoadError as exc:
        print(f"\nОШИБКА: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
