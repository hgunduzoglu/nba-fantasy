"""Boştaki oyuncular: kalan sezon için en iyi al + bırak çiftleri (README §13.13)."""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import streamlit as st

from fdo.inseason.waiver import drop_ranking, waiver_table
from fdo.inseason.weeks import league_weeks
from fdo.schedule.calendar import normalize_team
from fdo.trade.data import ROS
from fdo.trade.strategy import CATEGORIES
from fdo.types import CATEGORY_LABELS
from fdo.ui import trade_common as tc
from fdo.ui.analysis import POSITION_FILTERS, gain_css

data, eng, mine, day = tc.page("Boştaki Oyuncular")
lg = eng.league
names = data.players["name"]
strategy = tc.strategy_widget(eng, mine, f"fa_s_{lg.league_id}_{mine}", "Senin stratejin")


@st.cache_resource(show_spinner="Boştaki oyuncular kadrona göre değerlendiriliyor…")
def _table(_eng, fingerprint: str, league_id: str, team: str, utilization: float, strategy) -> pd.DataFrame:
    return waiver_table(_eng, team, strategy, top=150)


@st.cache_resource(show_spinner=False)
def _drops(_eng, fingerprint: str, league_id: str, team: str, utilization: float, strategy) -> pd.DataFrame:
    return drop_ranking(_eng, team, strategy)


t = _table(eng, data.fingerprint, lg.league_id, mine, eng.utilization, strategy)
if t.empty:
    st.info("Boştaki modellenebilir oyuncu ya da bırakılabilecek oyuncu yok.")
    st.stop()

# bu hafta ve gelecek hafta maç sayıları (takvimden)
weeks = league_weeks(data.schedule, lg.settings, lg.config)
sched = data.schedule.assign(game_date=pd.to_datetime(data.schedule["game_date"]).dt.date)
teams_on: dict[dt.date, set[str]] = {
    d: set(g["home_team"].map(normalize_team)) | set(g["away_team"].map(normalize_team))
    for d, g in sched.groupby("game_date")}
wk = weeks.week_of(day)


def games(team: str, days: list[dt.date]) -> int:
    team = normalize_team(team) if isinstance(team, str) and team else ""
    return sum(team in teams_on.get(d, ()) for d in days)


this_days = weeks.days(wk, day) if wk else []
next_days = weeks.days(wk + 1) if wk and wk + 1 in weeks.weeks.index else []

c = st.columns([2, 2, 2])
pos = c[0].selectbox("Pozisyon", POSITION_FILTERS, key="fa_pos")
hide_out = c[1].checkbox("Out / takımda olmayanları gizle", value=True, key="fa_hide")
n_show = c[2].selectbox("Göster", [25, 50, 100, 150], index=1, key="fa_n")
v = t.copy()
if hide_out:
    v = v[~v["status"].isin(["O", "NA", "INJ"])]
if pos != "Hepsi":
    want = {"G": {"PG", "SG"}, "F": {"SF", "PF"}}.get(pos, {pos})
    v = v[v["positions"].str.split(",").map(lambda ps: bool(want & set(ps)))]
v = v.head(int(n_show)).reset_index(drop=True)

ros = data.stats[ROS]
per_game = ros[["pts", "reb", "ast", "fg3m", "stl", "blk"]].div(ros["gp"], axis=0)
labels = [CATEGORY_LABELS[c_] for c_ in CATEGORIES]
shown = pd.DataFrame({
    "Al": v["name"], "Poz": v["positions"], "Takım": v["nba_team"], "Durum": v["status"],
    "Bırak": v["drop_name"], "Strateji Δ": v["score"], "ΔECW": v["delta_ecw"],
    **{lab: 100 * v[f"d_{c_}"] for c_, lab in zip(CATEGORIES, labels)},
    f"Maç (bu hafta, {len(this_days)} gün)": [games(tm, this_days) for tm in v["nba_team"]],
    "Maç (gelecek hafta)": [games(tm, next_days) for tm in v["nba_team"]],
    "ROS GP": ros.loc[v["add"], "gp"].to_numpy(float),
    "PTS/REB/AST": [f"{a:.1f} / {b:.1f} / {c_:.1f}" for a, b, c_ in
                    per_game.loc[v["add"], ["pts", "reb", "ast"]].to_numpy()],
})
vmax = float(np.nanquantile(np.abs(shown[labels].to_numpy(float)), .95)) if len(shown) else 1.0
smax = float(np.nanquantile(np.abs(shown["Strateji Δ"]), .95)) if len(shown) else 1.0
styler = (shown.style
          .format({"Strateji Δ": "{:+.3f}", "ΔECW": "{:+.3f}", "ROS GP": "{:.0f}", **{lab: "{:+.1f}" for lab in labels}})
          .map(lambda x: gain_css(x, vmax), subset=labels)
          .map(lambda x: gain_css(x, smax), subset=["Strateji Δ"]))
st.dataframe(styler, hide_index=True, width="stretch", height=min(35 * (len(shown) + 1) + 3, 900))
st.caption("Her boştaki oyuncu için kadrondan en iyi bırakma eşi. **Strateji Δ**: kalan sezonda rakip başına beklenen "
           "kategori galibiyetinin stratejine göre değişimi; **ΔECW** ağırlıksız. Kategori sütunları kazanma "
           "olasılığındaki puan değişimi (ortalama rakibe karşı). Pozisyon kuralı: bırakma sonrası doldurulamayan "
           "aktif slot artmaz. Waiver durumu, Can't Cut listesi ve kalan alım hakkı doğrulanmadı. "
           "Bu haftalık eşleşme için 'Bu Hafta' sayfasındaki streaming planına bak.")

with st.expander("Kadrondaki en kolay yerine konan oyuncular"):
    d = _drops(eng, data.fingerprint, lg.league_id, mine, eng.utilization, strategy)
    if d.empty:
        st.write("Kadrondaki her oyuncu boştaki seçeneklerden değerli görünüyor.")
    else:
        st.dataframe(pd.DataFrame({"Bırak": d["drop_name"], "Yerine en iyi": d["name"], "Strateji Δ": d["score"],
                                   "ΔECW": d["delta_ecw"]}).style.format({"Strateji Δ": "{:+.3f}", "ΔECW": "{:+.3f}"}),
                     hide_index=True, width="stretch")
        st.caption("Pozitif fark: o oyuncunun yerine boştaki biri alınırsa takım kalan sezonda güçlenir.")
