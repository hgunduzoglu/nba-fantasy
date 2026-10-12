"""Sentetik veri üretir (README §5.7).

    python scripts/make_synthetic.py --n 400 --seed 7 --out data/synthetic/
"""

from __future__ import annotations

import argparse
import sys

from fdo.config import load_config
from fdo.ingest import load_dataset
from fdo.ingest.synthetic import write_synthetic


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=400, help="oyuncu sayısı")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="data/synthetic/")
    ap.add_argument("--as-of", default=None, help="YYYY-MM-DD (varsayılan: bugün)")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")

    config = load_config()
    paths = write_synthetic(args.out, args.n, args.seed, config, args.as_of)
    ds, report = load_dataset(paths["players"], paths["projections"], paths["adp"], config=config)
    for kind, p in paths.items():
        print(f"{kind:12s} -> {p}")
    print(f"Validasyon: {report.summary()}")
    for msg in report.errors + report.warnings:
        print("  -", msg)
    if ds is not None:
        print("adp_status dağılımı:", ds.adp["adp_status"].value_counts().to_dict())
    return 0 if ds is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
