"""Sezon simülasyonu: playoff ve şampiyonluk olasılıkları, kalan fikstür (README §13.14)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from fdo.inseason.weekly import Stint
from fdo.ui import season_common as sc
from fdo.ui import trade_common as tc
from fdo.ui.analysis import gain_css

data, eng, mine, day = tc.page("Sezon Simülasyonu")
lg = eng.league
sim = sc.season_sim(eng)
if sim is None:
    st.info("Bu lig için fikstür bulunamadı. data/real altına fixtures*.csv (league_id, team_id, week, "
            "opponent_team_id) koy.")
    st.stop()

c1, c2 = st.columns(2)
n = c1.select_slider("Simülasyon sayısı", [500, 1000, 2000, 5000], value=sc.DEFAULT_SIMS, key="season_n")
c2.select_slider("Takım gücü belirsizliği", [0.0, 0.03, 0.06, 0.10, 0.15], value=sc.DEFAULT_SD, key="season_sd",
                 format_func=lambda v: f"±%{100 * v:.0f}",
                 help="Kalan sezon projeksiyonunun hatası: her simülasyonda her takımın gücü sezon boyu bu kadar "
                      "sapabilir. 0 = güçler kesin bilinir (aşırı kesin olasılıklar). Kalibre edilmedi; takas ve "
                      "öneri etkileri de bu ayarla hesaplanır.")
res = sc.run(sim, eng, n_sims=n, team=mine)
t = res.table
me = t.loc[mine]
rounds = len(sim.playoff_weeks)
byes = max(0, 2 ** rounds - res.playoff_size) if rounds else 0

st.subheader(lg.teams[mine])
m = st.columns(5)
m[0].metric(f"Playoff ({res.playoff_size} takım)", f"{me.p_playoff:.0%}")
m[1].metric("Bay (ilk tur yok)" if byes else "Normal sezon 1.si", f"{(me.p_bye if byes else me.p_first):.0%}")
m[2].metric("Şampiyonluk", f"{me.p_champion:.1%}")
m[3].metric("Ortalama sıra", f"{me.mean_seed:.1f}")
m[4].metric("Beklenen kayıt", f"{me.exp_wins:.0f}-{me.exp_losses:.0f}-{me.exp_ties:.0f}")
for note in res.notes:
    st.warning(note)
st.caption(f"Başlangıç: {res.start_week}. hafta · {res.n_sims} simülasyon · playoff haftaları "
           f"{', '.join(map(str, sim.playoff_weeks))} · reseeding {'açık' if sim.reseed else 'kapalı'}. "
           "Kadrolar sezon boyu sabit kabul edilir.")

st.subheader("Lig")
view = t.sort_values("mean_seed").copy()
show = pd.DataFrame({
    "Takım": [x + (" ★" if i == mine else "") for i, x in zip(view.index, view["team"])],
    "Şu an": view["record_now"] if "record_now" in view else "",
    "Beklenen W-L-T": [f"{a:.0f}-{b:.0f}-{c:.0f}" for a, b, c in zip(view.exp_wins, view.exp_losses, view.exp_ties)],
    "Beklenen %": view["exp_pct"], "Ort. sıra": view["mean_seed"], "P(playoff)": view["p_playoff"],
    ("P(bay)" if byes else "P(1.)"): view["p_bye"] if byes else view["p_first"], "P(şampiyon)": view["p_champion"],
})
prob_cols = ["P(playoff)", "P(bay)" if byes else "P(1.)", "P(şampiyon)"]
st.dataframe(show.style.format({"Beklenen %": "{:.3f}", "Ort. sıra": "{:.1f}", **{c: "{:.0%}" for c in prob_cols}})
             .map(lambda v: gain_css(v - .5, .5), subset=["P(playoff)"])
             .map(lambda v: gain_css(v, max(.05, float(view["p_champion"].max()))), subset=["P(şampiyon)"]),
             hide_index=True, width="stretch", height=36 * (len(show) + 1) + 3)

st.subheader("Kalan fikstürün")
s = res.schedule
if len(s):
    sched = pd.DataFrame({"Hafta": s["week"], "Başlangıç": [f"{d:%d.%m}" if d is not None else "" for d in s["start"]],
                          "Rakip": s["opponent_name"], "Beklenen kategori": s["exp_cats"], "P(kazan)": s["p_win"]})
    st.dataframe(sched.style.format({"Beklenen kategori": "{:.2f}", "P(kazan)": "{:.0%}"})
                 .map(lambda v: gain_css(v - .5, .4), subset=["P(kazan)"]), hide_index=True, width="stretch",
                 height=min(36 * (len(sched) + 1) + 3, 720))
    st.caption("Her hafta kendi NBA takvimiyle (maç sayıları değişir) ve günlük kadro yerleşimiyle. İçinde "
               "bulunulan hafta güncel sakatlıklarla, sonrakiler tam kadroyla hesaplanır.")

if sim.playoff_weeks:
    st.subheader("Playoff haftalarında sayılan maç")
    rows = []
    for w in sim.playoff_weeks:
        days = sim.weeks.days(w)
        counts = {tid: int(sim.model.team_week(tid, [Stint(p, slot=k) for k, p in enumerate(lg.rosters[tid])],
                                                days, use_status=False).counted.sum()) for tid in eng.team_ids}
        avg = sum(counts.values()) / len(counts)
        rows.append({"Hafta": w, "Tarih": f"{days[0]:%d.%m}–{days[-1]:%d.%m}", "Senin": counts[mine],
                     "Lig ortalaması": avg, "Fark": counts[mine] - avg})
    st.dataframe(pd.DataFrame(rows).style.format({"Lig ortalaması": "{:.1f}", "Fark": "{:+.1f}"})
                 .map(lambda v: gain_css(v, 6), subset=["Fark"]), hide_index=True, width="stretch")
    st.caption("Günlük lineup'ta aktif slota yerleşen maç sayısı (bütün kadro, sakatlık durumundan bağımsız). "
               "Playoff haftasında fazla maç oynayan oyuncular takas/alım için değerlidir.")

prev = st.session_state.get("trade_analysis_result")
if prev:
    result = prev[1]
    if result.request.team_a in eng.team_index and result.request.team_b in eng.team_index \
            and set(result.rosters_after) == set(eng.team_ids):
        st.divider()
        names = data.players["name"]
        st.markdown("**Son analiz edilen takas:** " + ", ".join(names[p] for p in result.request.give_a) + " ⇄ "
                    + ", ".join(names[p] for p in result.request.give_b))
        sc.show_trade_effect(eng, result, key="season_trade")
