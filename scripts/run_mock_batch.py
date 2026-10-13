"""N tam mock üretir ve gerçekçilik raporu çıkarır (README §7).

    python scripts/run_mock_batch.py --n 500 --seed 1 --data data/synthetic/
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

from fdo.bots.universe import build_universe
from fdo.config import load_config
from fdo.ingest.load import find_data_files, load_data_dir
from fdo.realism.metrics import compute_metrics, run_mock_batch
from fdo.realism.report import build_report


def find_files(data_dir: Path) -> dict[str, Path]:
    """Geriye dönük uyumluluk: ``fdo.ingest.load.find_data_files`` (zorunlu üç dosya yoksa çıkar)."""
    out = find_data_files(data_dir)
    for kind in ("players", "projections", "adp"):
        if kind not in out:
            raise SystemExit(f"{data_dir} içinde {kind}*.csv bulunamadı")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--data", default="data/synthetic/")
    ap.add_argument("--out", default="reports/")
    ap.add_argument("--external", default=None, help="opsiyonel gerçek draft log CSV'si (KS testi)")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")

    config = load_config()
    ds, report = load_data_dir(args.data, config)
    if ds is None:
        print("Veri yüklenemedi:", *report.errors, sep="\n  - ")
        return 1
    universe = build_universe(ds, config)

    t0 = time.perf_counter()
    batch = run_mock_batch(universe, config, args.n, args.seed,
                           progress=lambda i, n: print(f"\r{i}/{n} mock", end="", flush=True))
    elapsed = time.perf_counter() - t0
    print(f"\n{args.n} mock: {elapsed:.1f} s")

    external = pd.read_csv(args.external) if args.external else None
    metrics = compute_metrics(batch, universe, config, external)
    md = build_report(metrics, config, data_label=f"{args.data} (hash {ds.content_hash})",
                      is_synthetic=ds.is_synthetic)
    md += f"\n_Süre: {args.n} mock {elapsed:.1f} s_\n"
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"realism_n{args.n}_seed{args.seed}.md"
    path.write_text(md, encoding="utf-8")
    print(f"Rapor: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
