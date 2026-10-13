"""Tamamlanmış bir draft'ta kullanıcının pick'lerini advisor önerileriyle karşılaştırır.

Kullanıcının her pick'inde draft o ana geri sarılır; advisor (hızlı mod) kullanıcının gerçek seçimi
pinlenmiş olarak çalışır. Rapor: advisor'ın en iyisi, kullanıcının seçiminin E[W]'si, CRN eşleşmeli fark
(regret ± SE) ve sırası; sonunda 14/16 kadronun hepsi gerçek oyuncularla ECW sıralaması.

Log ``import_names`` biçimindedir (``pick, player, auto, user``; ``convert_draft_results.py`` çıktısı).
Havuz dışı (ADP'si ve projeksiyonu olmayan) pick'lerin yerine kimsenin seçmediği projeksiyonsuz bir
oyuncu yer tutucu olarak konur (rapor bunu belirtir).

    python scripts/review_draft.py --log data/real/draft_logs/draft_real.csv --league config/league_14.yaml
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from fdo.advisor.pairs import recommend
from fdo.advisor.simulate import make_engine, prepare_context, team_vectors
from fdo.config import load_config
from fdo.draft.events import DraftLog
from fdo.draft.io import import_names
from fdo.ingest.load import load_data_dir
from fdo.matchup.ecw import ecw_matrix, opponent_category_mean, team_ecw
from fdo.realism.report import md_table
from fdo.types import CATEGORY_LABELS


def with_placeholders(log: DraftLog, universe, has_vec) -> tuple[DraftLog, list[str]]:
    """Havuz dışı pick'leri kimsenin seçmediği projeksiyonsuz (yoksa en yüksek ADP'li) oyuncuyla değiştirir."""
    taken = {p.player_id for p in log.picks}
    spare = [str(universe.ids[i]) for i in np.argsort(-universe.adp)
             if str(universe.ids[i]) not in taken and not has_vec[i]]
    spare += [str(universe.ids[i]) for i in np.argsort(-universe.adp) if str(universe.ids[i]) not in taken]
    notes, out = [], DraftLog(log.teams, log.rounds, log.third_round_reversal)
    for p in log.picks:
        pid = p.player_id
        if pid not in universe.index:
            sub = spare.pop(0)
            notes.append(f"pick {p.overall_pick}: {pid} havuz dışı → yer tutucu {sub}")
            pid = sub
        out = out.append(type(p)(p.overall_pick, p.round, p.seat, pid, p.source, p.observed_at))
    return out, notes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", required=True)
    ap.add_argument("--league", default=None, help="lig config'i (varsayılan config/league.yaml)")
    ap.add_argument("--data", default="data/real/")
    ap.add_argument("--mode", choices=["fast", "full"], default="fast")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="reports/")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")

    cfg = load_config(args.league) if args.league else load_config()
    ds, rep = load_data_dir(args.data, cfg)
    if ds is None:
        print("Veri yüklenemedi:", *rep.errors, sep="\n  - ")
        return 1
    log, _ = import_names(Path(args.log).read_text(encoding="utf-8"), ds.players, cfg)
    seats = {p.seat for p in log.picks if p.source == "import:user"}
    if seats != {cfg.league.my_seat}:
        print(f"Kullanıcı pick'lerinin koltuğu {sorted(seats)}, config my_seat {cfg.league.my_seat}")
        return 1
    ctx = prepare_context(ds, cfg, args.seed)
    u = ctx.universe
    log, notes = with_placeholders(log, u, ctx.has_vec)
    names = ds.names()

    rows = []
    t0 = time.perf_counter()
    for p in [p for p in log.picks if p.source == "import:user"]:
        prefix = log.truncate(p.overall_pick)
        res = recommend(ctx, prefix, mode=args.mode, pinned_players=[p.player_id], conditional_fill=True)
        mine = next(r for r in res.pairs if r.players == (p.player_id,))
        best = res.pairs[0]
        rank = [r.label for r in res.pairs].index(mine.label) + 1
        rows.append({"pick": p.overall_pick, "tur": p.round, "seçimin": mine.label, "E[W]": mine.mean,
                     "advisor": best.label, "E[W] advisor": best.mean, "fark": mine.regret,
                     "fark_SE": mine.regret_se, "sıra": f"{rank}/{len(res.pairs)}",
                     "aynı kademe": mine.tier == best.tier})
        print(f"pick {p.overall_pick}: {mine.label} ({mine.mean:.3f}) vs {best.label} ({best.mean:.3f}) "
              f"fark {mine.regret:.3f} ± {mine.regret_se:.3f}", flush=True)
    picks = pd.DataFrame(rows)

    eng = make_engine(ctx, log, 1, seed=0, cache_jitter=False)
    teams = team_vectors(eng, ctx.vecs, ctx.base_fill, eng.total + 1)[0]
    mat = ecw_matrix(teams, cfg)
    team_names = {}
    raw = pd.read_csv(args.log)
    for r in raw.itertuples():
        seat = log.seat_for(int(r.pick))
        team_names.setdefault(seat, getattr(r, "fantasy_team", f"S{seat}"))
    cats = [CATEGORY_LABELS[c] for c in cfg.categories]
    final = pd.DataFrame(opponent_category_mean(mat), columns=cats)
    final.insert(0, "ECW", team_ecw(mat))
    final.insert(0, "takım", [team_names.get(s, f"S{s}") + (" ★" if s == cfg.league.my_seat else "")
                             for s in range(1, cfg.league.teams + 1)])
    final = final.sort_values("ECW", ascending=False).reset_index(drop=True)
    final.index += 1

    total_regret = float(picks["fark"].sum())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Draft incelemesi — {cfg.league.name or 'lig'}", "",
        f"- Log: `{args.log}`; {cfg.league.teams} takım × {cfg.league.rounds} tur; koltuk {cfg.league.my_seat}",
        f"- Advisor: {args.mode} mod, seed {args.seed}; süre {time.perf_counter() - t0:.0f} s",
        "- E[W]: sonraki turn'e kadar rollout + doldurma, rakip başına beklenen kategori galibiyeti (0–9). "
        "Fark: advisor'ın en iyisi − seçimin (CRN eşleşmeli); aynı kademe = istatistiksel olarak ayırt edilemez.",
        *[f"- Not: {n}" for n in notes], "",
        "## Pick'ler", "", md_table(picks.round(3), index=False), "",
        f"Toplam fark: {total_regret:.3f} (pick başına bağımsız; birikimli etki değildir).", "",
        "## Final kadrolar (gerçek oyuncular, projeksiyona göre ECW)", "", md_table(final.round(2)), "",
    ]
    (out / "draft_review.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"rapor -> {out / 'draft_review.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
