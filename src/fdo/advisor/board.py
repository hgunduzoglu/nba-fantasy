"""Kategori panosu: uygun oyuncuların kullanıcının takımına kategori bazında katkısı (README §13.10).

Draft ekranında advisor'ın yanında, her durumda (sıra kullanıcıda olmasa da) gösterilir:

* ``ΔP_c(i) = P_c(R ∪ {i} ∪ fill) − P_c(R ∪ F(t₁) ∪ fill)``: oyuncu kullanıcının sıradaki pick'inde
  (``t₁``) alınırsa c kategorisinde 15 rakibe karşı ortalama kazanma olasılığının, aynı pick'in nötr
  doldurma profiline göre değişimi. Toplamı ΔECW'dir (``delta_ecw`` ile aynı).
* ``team_p``: kullanıcının mevcut kadrosu + kalan pick'lerin doldurma profili ile kategori P'leri
  (takımın nerede güçlü/zayıf olduğu).
* ``z_c``: oyuncunun dengeli z-skoru (takımdan bağımsız değer; hashtagbasketball tarzı görünüm);
  ``perf_level`` z'yi Elite … Poor kademelerine çevirir.
* ``p_avail``: oyuncunun kullanıcının ilgili pick'ine kadar kalma olasılığı (bot simülasyonu). Sıra
  kullanıcıdaysa sonraki turn'e, değilse sıradaki pick'e kadar.

Statik rakiplere karşı hesaplanır (rollout yok); hızlıdır ve advisor'ın E[W] sıralamasının yerine
geçmez, onu açıklar.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from fdo.advisor.pairs import setup_problem
from fdo.advisor.simulate import AdvisorContext, make_engine, sub_seed
from fdo.advisor.survival import survival
from fdo.draft.events import DraftLog
from fdo.matchup.ecw import ecw_vs
from fdo.matchup.fill import FillTable

STREAM_BOARD = 5

#: Maç başı istatistik sütunları (kategori → projeksiyon ifadesi).
STAT_FORMULAS = {
    "FG_PCT": lambda p: p["fgm"] / p["fga"],
    "FT_PCT": lambda p: p["ftm"] / p["fta"],
    "FG3M": lambda p: p["fg3m"],
    "PTS": lambda p: p["pts"],
    "REB": lambda p: p["reb"],
    "AST": lambda p: p["ast"],
    "STL": lambda p: p["stl"],
    "BLK": lambda p: p["blk"],
    "TOV": lambda p: p["tov"],
}


#: z-skoru kademeleri (alt sınır, ad): hashtagbasketball'daki Elite/Great/Good/Avg/Below/Poor görünümü.
PERF_LEVELS = ((1.5, "Elite"), (1.0, "Great"), (0.5, "Good"), (-0.5, "Avg"), (-1.0, "Below"),
               (-np.inf, "Poor"))


def perf_level(z: float) -> str:
    if z is None or np.isnan(z):
        return ""
    return next(name for lo, name in PERF_LEVELS if z >= lo)


def scarcity(table: pd.DataFrame, categories, levels=("Elite", "Great", "Good")) -> pd.DataFrame:
    """Kategori başına üst kademelerdeki oyuncu sayısı (satır: kademe, sütun: kategori)."""
    out = {c: [sum(perf_level(z) == lv for z in table[f"z_{c}"]) for lv in levels] for c in categories}
    return pd.DataFrame(out, index=list(levels))


@dataclass
class CategoryBoard:
    pick: int                      # kullanıcının değerlendirilen pick'i (t₁)
    on_clock: bool                 # sıra kullanıcıda mı
    avail_pick: int | None         # p_avail'in ölçüldüğü pick
    categories: tuple[str, ...]
    team_p: np.ndarray             # (C,)
    table: pd.DataFrame            # oyuncu başına: kimlik, ΔECW, Δ_c, z_c, stat_c, p_avail
    weights: np.ndarray | None


def category_board(ctx: AdvisorContext, log: DraftLog, *, fill: FillTable | None = None,
                   category_weights: dict[str, float] | None = None, n_sims: int = 64,
                   opponent_probs: np.ndarray | None = None, seed: int | None = None) -> CategoryBoard:
    cfg = ctx.config
    u = ctx.universe
    fill = fill or ctx.base_fill
    prob = setup_problem(ctx, log, fill, category_weights, upcoming=True)
    t1 = prob.turn[0]
    cats = tuple(cfg.categories)

    base = prob.roster_vec + prob.fill_sum([n for n in prob.turn + prob.after_turn if n != t1])
    team_p = ecw_vs(base + fill.means[t1], prob.opp_static, cfg).mean(axis=-2)          # (C,)
    idx = np.flatnonzero(prob.available & ctx.has_vec)
    p_with = ecw_vs(base[None, :] + ctx.vecs[idx], prob.opp_static, cfg).mean(axis=-2)  # (m, C)
    d = p_with - team_p

    on_clock = log.next_seat == prob.user
    target = (prob.next_turn[0] if prob.next_turn else None) if on_clock else t1
    p_avail = np.full(len(idx), np.nan)
    if target is not None and target > log.next_pick and n_sims > 0:
        eng = make_engine(ctx, log, n_sims, sub_seed(ctx.seed if seed is None else seed, STREAM_BOARD),
                          cache_jitter=False, seat_profile_probs=opponent_probs)
        eng.run_until(target, skip_seat=prob.user)
        p_avail = survival(eng)[0][idx]

    ids = [str(u.ids[i]) for i in idx]
    names = ctx.dataset.names()
    players = ctx.dataset.players.set_index("player_id")
    proj = ctx.dataset.projections.set_index("player_id").reindex(ids)
    table = pd.DataFrame({
        "player_id": ids,
        "name": [str(names.get(p, p)) for p in ids],
        "positions": [",".join(sorted(players.at[p, "positions"])) for p in ids],
        "nba_team": [players.at[p, "nba_team"] for p in ids],
        "injury": proj["injury_status"].fillna("").to_numpy() if "injury_status" in proj else "",
        "adp": u.adp[idx],
        "gp": proj["projected_gp"].to_numpy(float),
        "z_total": u.zcat[idx].sum(axis=1),
        "delta_ecw": d.sum(axis=1),
        "p_avail": p_avail,
    })
    w = prob.cat_weights
    table["score"] = (d * w).sum(axis=1) if w is not None else table["delta_ecw"]
    for j, c in enumerate(cats):
        table[f"d_{c}"] = d[:, j]
    for j, c in enumerate(cats):
        table[f"z_{c}"] = u.zcat[idx, j]
    with np.errstate(divide="ignore", invalid="ignore"):
        for c in cats:
            table[f"s_{c}"] = STAT_FORMULAS[c](proj).to_numpy(float) if c in STAT_FORMULAS else np.nan
    for col in ("fgm", "fga", "ftm", "fta"):
        table[col] = proj[col].to_numpy(float)
    table = table.sort_values("score", ascending=False, kind="stable").reset_index(drop=True)
    return CategoryBoard(pick=t1, on_clock=on_clock, avail_pick=target, categories=cats, team_p=team_p,
                         table=table, weights=w)
