"""Gerçek draft log'larından bot σ₀/σ₁ uyumu ve survival güvenilirliği (README §13.6).

Log biçimleri:
* ``draft_log`` şeması (Mock Draft sayfasının export'u; ``player_id`` kolonlu CSV/JSON),
* isimli sonuç: ``pick``, ``player`` (oyuncu adı, Yahoo yazımı) ve opsiyonel ``auto`` (Yahoo'nun
  otomatik seçtiği pick; momentlerden dışlanır) kolonlu CSV/TSV.

Log'lar farklı büyüklükte bir ligden olabilir (Yahoo'da 16 takımlı mock yok): ``--teams``/``--rounds``.

    python scripts/calibrate_bots.py --logs "data/real/draft_logs/*.csv" --teams 14
"""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import yaml

from fdo.bots.universe import build_universe
from fdo.calibration.bots import (
    fit_sigma,
    league_config,
    survival_brier,
    logs_to_matrix,
    simulate_matrix,
    survival_reliability,
    user_checkpoints,
    with_sigma,
)
from fdo.config import load_config
from fdo.draft import io as draft_io
from fdo.draft.events import DraftError
from fdo.ingest.load import load_data_dir
from fdo.realism.report import md_table


def floats(text: str) -> tuple[float, ...]:
    return tuple(float(x) for x in text.split(","))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--logs", required=True, help="glob, örn. 'data/real/draft_logs/*.csv'")
    ap.add_argument("--data", default="data/real/")
    ap.add_argument("--sigma0", default="0.5,1.5,3,5")
    ap.add_argument("--sigma1", default="0.08,0.12,0.18,0.25,0.35")
    ap.add_argument("--objective", choices=["brier", "moments"], default="brier",
                    help="brier: sabit kümede survival Brier (varsayılan); moments: pick − A momentleri")
    ap.add_argument("--sims", type=int, default=60, help="ızgara noktası başına simülasyon")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--teams", type=int, default=None, help="log'ların takım sayısı (varsayılan: lig)")
    ap.add_argument("--rounds", type=int, default=None, help="log'ların tur sayısı (varsayılan: lig)")
    ap.add_argument("--out", default="reports/")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")

    cfg = load_config()
    ds, rep = load_data_dir(args.data, cfg)
    if ds is None:
        print("Veri yüklenemedi:", *rep.errors, sep="\n  - ")
        return 1
    paths = sorted(glob.glob(args.logs))
    if not paths:
        print(f"Log bulunamadı: {args.logs}")
        return 1
    universe = build_universe(ds, cfg)
    cfg = league_config(cfg, args.teams or cfg.league.teams, args.rounds)
    logs = []
    for p in paths:
        text = Path(p).read_text(encoding="utf-8-sig")
        try:
            if "player_id" in text.splitlines()[0] or text.lstrip().startswith(("{", "#")):
                logs.append(draft_io.import_log(text, cfg)[0])
            else:
                logs.append(draft_io.import_names(text, ds.players, cfg)[0])
        except DraftError as e:
            print(f"{p}: {e}")
            return 1
    print(f"{len(logs)} log, {cfg.league.teams} takım × {cfg.league.rounds} tur")

    def progress(i, n):
        print(f"\rızgara {i}/{n}", end="", flush=True)

    fit = fit_sigma(logs, ds, universe, cfg, sigma0_grid=floats(args.sigma0), sigma1_grid=floats(args.sigma1),
                    n_sims=args.sims, seed=args.seed, objective=args.objective, progress=progress)
    print(f"\nEn iyi: {fit.best} (mevcut: σ₀={cfg.model.bots.sigma0}, σ₁={cfg.model.bots.sigma1})")

    obs, _ = logs_to_matrix(logs, universe)
    checkpoints = user_checkpoints(cfg)
    best_cfg = cfg.with_overrides({"model": {"bots": fit.best}})
    rel, fixed = {}, {}
    for label, c, u in (("mevcut", cfg, universe), ("uyum", best_cfg, with_sigma(universe, ds, best_cfg))):
        sim = simulate_matrix(u, c, max(200, args.sims), args.seed + 1)
        rel[label] = survival_reliability(sim, obs, checkpoints, universe.n)
        fixed[label] = survival_brier(sim, obs, universe)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Bot kalibrasyonu (README §13.6)", "",
        f"- Log: {len(logs)} draft (`{args.logs}`), {cfg.league.teams} takım × {cfg.league.rounds} tur; "
        f"evrende olmayan pick: {fit.missing_picks}; otomatik (momentlerden dışlanan) pick: {fit.auto_picks}",
        f"- σ'sı σ₀ + σ₁·A ile belirlenen oyuncu payı: {fit.param_share:.0%}",
        f"- Izgara: σ₀ ∈ {args.sigma0}, σ₁ ∈ {args.sigma1}; nokta başına {args.sims} simülasyon (CRN)",
        f"- Ölçüt: {args.objective}",
        f"- **En iyi: σ₀ = {fit.best['sigma0']}, σ₁ = {fit.best['sigma1']}**",
        f"- Survival Brier (sabit küme, ayrı {max(200, args.sims)} simülasyon): mevcut {fixed['mevcut']:.4f}, "
        f"uyum {fixed['uyum']:.4f}", "",
        "## Izgara (ilk 10)", "", md_table(fit.grid.head(10), index=False), "",
        "## `pick − A` momentleri", "", "### Gözlenen", "", md_table(fit.observed), "",
        "### Uyum", "", md_table(fit.fitted), "", "### Mevcut config", "", md_table(fit.current), "",
        "## Survival güvenilirliği (kullanıcı pick'lerinde; Brier yalnızca 0.01–0.99 tahminler, σ'lar arası "
        "karşılaştırma için üstteki sabit küme Brier'i kullanılmalı)", "",
    ]
    for label, (table, brier) in rel.items():
        lines += [f"### {label} — Brier {brier:.4f}", "", md_table(table), ""]
    lines += ["## `config/model.yaml` için", "", "```yaml",
              yaml.safe_dump({"bots": fit.best}, sort_keys=False).strip(), "```", ""]
    (out / "bot_calibration.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"rapor -> {out / 'bot_calibration.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
