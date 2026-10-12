"""Performans bütçelerini ölçer (README §11). Sonuçlar raporlanır, test eşiği değildir.

    python scripts/profile_advisor.py            # hepsi (500 mock batch hariç)
    python scripts/profile_advisor.py --batch    # 500 mock batch dahil
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

from fdo.advisor.pairs import recommend
from fdo.advisor.simulate import build_fill, player_vectors, prepare_context
from fdo.bots.mock import MockDraft
from fdo.bots.universe import build_universe
from fdo.config import load_config
from fdo.ingest import make_synthetic
from fdo.realism.metrics import run_mock_batch
from fdo.realism.report import md_table
from fdo.valuation import value_players
from fdo.valuation.weights import preset

TARGETS = {
    "Valuation (600 oyuncu, ağırlık değişimi)": 0.5,
    "Tek tam mock (208 pick, 15 bot)": 0.2,
    "500 mock batch": 90.0,
    "Doldurma tablosu (200 mock)": 40.0,
    "Advisor hızlı mod (S=200, 30 çift)": 15.0,
    "Advisor tam mod (S=500, 30 çift)": 45.0,
}


def timed(fn):
    t = time.perf_counter()
    out = fn()
    return time.perf_counter() - t, out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--batch", action="store_true", help="500 mock batch'i de ölç")
    ap.add_argument("--out", default="reports/")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")

    import pandas as pd

    cfg = load_config()
    rows = []

    ds600 = make_synthetic(600, np.random.default_rng(args.seed), cfg, seed=args.seed)
    value_players(ds600.projections, cfg)
    t, _ = timed(lambda: value_players(ds600.projections, cfg, weights=preset(cfg, "punt_FT")))
    rows.append(("Valuation (600 oyuncu, ağırlık değişimi)", t))

    ds = make_synthetic(400, np.random.default_rng(args.seed), cfg, seed=args.seed)
    universe = build_universe(ds, cfg)
    MockDraft(ds, cfg, 0, universe).play_to_end()
    t, _ = timed(lambda: MockDraft(ds, cfg, 1, universe).play_to_end())
    rows.append(("Tek tam mock (208 pick, 15 bot)", t))

    if args.batch:
        t, _ = timed(lambda: run_mock_batch(universe, cfg, 500, args.seed))
        rows.append(("500 mock batch", t))

    vecs, _ = player_vectors(ds, cfg, universe)
    t, _ = timed(lambda: build_fill(universe, cfg, vecs, 200, args.seed))
    rows.append(("Doldurma tablosu (200 mock)", t))

    ctx = prepare_context(ds, cfg, args.seed, universe=universe)
    m = MockDraft(ds, cfg, 3, universe)
    m.play_until_user()
    t, res = timed(lambda: recommend(ctx, m.log, mode="fast"))
    rows.append(("Advisor hızlı mod (S=200, 30 çift)", t))
    t, _ = timed(lambda: recommend(ctx, m.log, mode="full"))
    rows.append(("Advisor tam mod (S=500, 30 çift)", t))

    df = pd.DataFrame([{"işlem": k, "süre_s": v, "hedef_s": TARGETS[k], "durum": "OK" if v < TARGETS[k] else "AŞILDI"}
                       for k, v in rows])
    print(df.to_string(index=False))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "profile_advisor.md").write_text("# Performans ölçümü (README §11)\n\n" + md_table(df, index=False)
                                            + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
