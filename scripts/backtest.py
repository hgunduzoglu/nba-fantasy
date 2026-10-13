"""Strateji karşılaştırması (README §13.1).

    python scripts/backtest.py --data data/real/ --n 30 --strategies adp,z,g,ecw
    python scripts/backtest.py --data data/real/ --evaluator gamelogs --gamelogs data/real/gamelogs_nba_2026-27.csv

``noise`` değerlendiricisi gerçekleşen sezonu projeksiyon + gürültüden simüle eder (iyimser;
projeksiyon hatası modeldendir). ``gamelogs`` gerçekleşen maç kayıtlarını kullanır (draft'tan
sonraki sezonun log'ları gerekir; geçmiş sezonların sezon öncesi projeksiyon/ADP'si yoksa
bu veri setiyle yalnızca içinde bulunulan sezon sonunda anlamlıdır).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fdo.bots.universe import build_universe
from fdo.config import load_config
from fdo.evaluation import GameLogEvaluator, ProjectionNoiseEvaluator
from fdo.evaluation.backtest import build_strategies, run_backtest
from fdo.ingest import load_dataset
from fdo.ingest.load import load_table
from fdo.realism.report import md_table


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data/real/")
    ap.add_argument("--n", type=int, default=20, help="draft sayısı")
    ap.add_argument("--strategies", default="adp,z,g,ecw")
    ap.add_argument("--evaluator", choices=["noise", "gamelogs"], default="noise")
    ap.add_argument("--gamelogs", default=None)
    ap.add_argument("--projection-sd", type=float, default=0.12, help="noise: projeksiyon hatası (log σ)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="reports/")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")

    from run_mock_batch import find_files

    cfg = load_config()
    files = find_files(Path(args.data))
    ds, rep = load_dataset(files["players"], files["projections"], files["adp"], config=cfg)
    if ds is None:
        print("Veri yüklenemedi:", *rep.errors, sep="\n  - ")
        return 1
    universe = build_universe(ds, cfg)
    if args.evaluator == "gamelogs":
        if not args.gamelogs:
            print("--gamelogs gerekli")
            return 1
        logs, _, lrep = load_table(args.gamelogs, "gamelogs", players=ds.players, drop_unmatched=True)
        if logs is None:
            print("Game log yüklenemedi:", *lrep.errors[:10], sep="\n  - ")
            return 1
        ev = GameLogEvaluator(logs, ds.positions(), cfg)

        def factory(_):
            return ev
    else:
        def factory(d):
            return ProjectionNoiseEvaluator(ds.projections, cfg, seed=d, projection_sd=args.projection_sd)

    names = [s.strip() for s in args.strategies.split(",") if s.strip()]
    strategies = build_strategies(names, ds, cfg, universe, args.seed)
    res = run_backtest(ds, cfg, universe, strategies, factory, args.n, seed=args.seed,
                       progress=lambda i, n: print(f"\r{i}/{n}", end="", flush=True))
    print()
    summary = res.summary()
    print(summary.round(3).to_string())
    base = "adp" if "adp" in names else names[0]
    paired = res.paired(base)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    text = "\n".join([
        "# Backtest (README §13.1)", "",
        f"- Veri: `{args.data}`, {args.n} draft, seed {args.seed}, değerlendirici: {args.evaluator}, "
        f"süre {res.elapsed:.0f} s", *[f"- {n}" for n in res.notes],
        f"- Koltuk {cfg.league.my_seat}; diğer 15 koltuk V1 bot karışımı; stratejiler aynı draft'ları görür (CRN).",
        "", "## Özet (eşleşme başına kategori galibiyeti, all-play)", "", md_table(summary), "",
        f"## `{base}`'e göre eşleşmeli fark", "", md_table(paired, index=False), "",
    ])
    (out / "backtest.md").write_text(text, encoding="utf-8")
    print(f"rapor -> {out / 'backtest.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
