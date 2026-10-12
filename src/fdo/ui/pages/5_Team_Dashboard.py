"""Sayfa 5 — Team Dashboard (README §6.6, §8).

Takım vektörleri: seçilen oyuncular + kalan pick'ler için doldurma profilleri.
FG%/FT% toplamdan hesaplanır (İlke 4). Matchup kategori ağırlıklarını okumaz (İlke 3).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from fdo.advisor.simulate import make_engine, team_vectors
from fdo.matchup.ecw import classify, ecw_matrix, opponent_category_mean, team_ecw
from fdo.matchup.team_totals import category_means
from fdo.types import CATEGORY_LABELS
from fdo.ui import common

common.page("5 · Team Dashboard")
cfg = common.config()
lg = cfg.league
mp = cfg.model.matchup
m = common.mock()
log = m.log
ctx = common.advisor_context()

eng = make_engine(ctx, log, 1, seed=0, cache_jitter=False)
teams = team_vectors(eng, ctx.vecs, ctx.base_fill, log.next_pick)[0]          # (T, 24)
mat = ecw_matrix(teams, cfg)
cats = [CATEGORY_LABELS[c] for c in cfg.categories]
seat_names = [f"S{s}" + (" (siz)" if s == lg.my_seat else "") for s in range(1, lg.teams + 1)]
real = [sum(1 for p in log.picks if p.seat == s) for s in range(1, lg.teams + 1)]

st.markdown(f"Pick {min(log.next_pick, lg.total_picks)} itibarıyla · doldurma: taban tablo "
            f"({ctx.base_fill.n_sims} sim) · " + common.UNCALIBRATED)
if max(real, default=0) < lg.rounds / 2:
    st.warning(f"Kadroların çoğu doldurma profili (en fazla {max(real, default=0)}/{lg.rounds} gerçek oyuncu): "
               "olasılıklar büyük ölçüde nötr doldurmaya dayanıyor.")

st.subheader("Takım × kategori ortalama P(win) (15 rakibe karşı)")
avg = pd.DataFrame(opponent_category_mean(mat), index=seat_names, columns=cats)
avg.insert(0, "ECW", team_ecw(mat))
avg["gerçek/doldurma"] = [f"{r}/{lg.rounds}" for r in real]
st.dataframe(avg.style.format({**{c: "{:.2f}" for c in cats}, "ECW": "{:.2f}"}).map(common.prob_bg, subset=cats),
             height=36 * (lg.teams + 1) + 5)

me = lg.my_seat - 1
st.subheader("Kullanıcı vs her rakip")
vs = pd.DataFrame(mat[me], index=seat_names, columns=cats).drop(index=seat_names[me])
vs.insert(0, "ECW", vs.sum(axis=1))
st.dataframe(vs.style.format("{:.2f}").map(common.prob_bg, subset=cats), height=36 * lg.teams + 5)

st.subheader("Kategorileriniz")
icons = {"kazanılabilir": "✅", "sınırda": "➖", "kaybedilmiş": "❌"}
mine = avg.loc[seat_names[me], cats]
cls = pd.DataFrame({
    "kategori": cats,
    "P(win)": mine.to_numpy(float).round(2),
    "durum": [f"{icons[c]} {c}" for c in (classify(p, mp.winnable_threshold, mp.lost_threshold) for p in mine)],
})
st.dataframe(cls, hide_index=True)
st.caption(f"Eşikler: P ≥ {mp.winnable_threshold} kazanılabilir, {mp.lost_threshold}–{mp.winnable_threshold} "
           f"sınırda, ≤ {mp.lost_threshold} kaybedilmiş.")

st.subheader("Beklenen haftalık takım değerleri")
vals = pd.DataFrame([category_means(teams[t], cfg) for t in range(lg.teams)], index=seat_names)
vals = vals.rename(columns=CATEGORY_LABELS)
fmt = {c: "{:.3f}" for c in ("FG%", "FT%")}
fmt.update({c: "{:.1f}" for c in vals.columns if c not in fmt})
st.dataframe(vals.style.format(fmt), height=36 * (lg.teams + 1) + 5)
st.caption("FG% = ΣFGM / ΣFGA ve FT% = ΣFTM / ΣFTA takım toplamlarından hesaplanır; yüzdelerin ortalaması alınmaz.")
