"""Bu hafta: H2H eşleşme olasılıkları, gün gün kadro ve streaming planı (README §13.13)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from fdo.inseason.fixtures import load_fixtures, opponent
from fdo.inseason.waiver import drop_ranking
from fdo.inseason.weekly import DEFAULT_OUT, WeekModel, acquisition_limit, vector_totals
from fdo.inseason.weeks import league_weeks
from fdo.trade.strategy import CATEGORIES
from fdo.types import CATEGORY_LABELS
from fdo.ui import trade_common as tc
from fdo.ui.analysis import gain_css

data, eng, mine, day = tc.page("Bu Hafta")
lg = eng.league
names = data.players["name"]
weeks = league_weeks(data.schedule, lg.settings, lg.config)
fixtures = load_fixtures(tc.DATA_DIR)

current = weeks.week_of(day)
if current is None:
    later = weeks.weeks.index[weeks.weeks["start"] > day]
    current = int(later.min()) if len(later) else int(weeks.weeks.index.max())
options = [w for w in weeks.weeks.index if w >= current]
wk = st.selectbox("Hafta", options, format_func=lambda w: f"{w}. hafta · {weeks.weeks.loc[w, 'start']:%d.%m}–"
                  f"{weeks.weeks.loc[w, 'end']:%d.%m}" + (" · playoff" if weeks.weeks.loc[w, "playoff"] else ""),
                  key=f"wk_week_{lg.league_id}")
start = day if wk == current else None
days = weeks.days(wk, start)
fx_opp = opponent(fixtures, lg.league_id, mine, wk)
others = [t for t in eng.team_ids if t != mine]
opp = st.selectbox("Rakip", others, index=others.index(fx_opp) if fx_opp in others else 0,
                   format_func=lambda t: lg.teams[t] + (" (fikstür)" if t == fx_opp else ""),
                   key=f"wk_opp_{lg.league_id}_{mine}_{wk}")
if fx_opp is None:
    st.caption("Bu hafta için fikstür kaydı yok; rakibi elle seç.")

c1, c2 = st.columns(2)
with c1:
    strategy = tc.strategy_widget(eng, mine, f"wk_s_{lg.league_id}_{mine}", "Senin stratejin")
with c2:
    sit_out = st.checkbox("O (out) durumundaki oyuncuları oynatma", value=True, key="wk_out")
    st.caption("NA (takımda değil) her zaman oynamaz; Q oynar. IL'deki oyuncular kadroda sayılmaz.")


@st.cache_resource(show_spinner="Haftalık model hazırlanıyor…")
def _model(_eng, fingerprint: str, league_id: str, utilization: float, strategy, out: tuple[str, ...]) -> WeekModel:
    return WeekModel(_eng, strategy=strategy, out_statuses=out)


out = DEFAULT_OUT if sit_out else tuple(s for s in DEFAULT_OUT if s != "O")
model = _model(eng, data.fingerprint, lg.league_id, eng.utilization, strategy, out)

acc_mine = acc_opp = None
started = wk == current and day > weeks.weeks.loc[wk, "start"]
if started:
    with st.expander("Bu haftanın şu ana kadarki skoru (Yahoo matchup sayfasından)", expanded=True):
        cols = ["FGM", "FGA", "FTM", "FTA", "3PTM", "PTS", "REB", "AST", "ST", "BLK", "TO"]
        keys = ["fgm", "fga", "ftm", "fta", "fg3m", "pts", "reb", "ast", "stl", "blk", "tov"]
        edited = st.data_editor(pd.DataFrame(0.0, index=["Sen", "Rakip"], columns=cols),
                                key=f"wk_acc_{lg.league_id}_{mine}_{opp}_{wk}")
        acc_mine = dict(zip(keys, edited.loc["Sen"].to_numpy(float)))
        acc_opp = dict(zip(keys, edited.loc["Rakip"].to_numpy(float)))
        if not any(acc_mine.values()) and not any(acc_opp.values()):
            st.warning(f"Hafta {weeks.weeks.loc[wk, 'start']:%d.%m}'de başladı. Skor girilmezse olasılıklar yalnızca "
                       f"kalan {len(days)} güne göredir.")

o = model.outlook(mine, opp, days, acc_mine=acc_mine, acc_opp=acc_opp, week=wk)
st.subheader(f"{lg.teams[mine]} – {lg.teams[opp]} · kalan {len(days)} gün ({days[0]:%d.%m}–{days[-1]:%d.%m})")
m = st.columns(5)
m[0].metric("Beklenen kategori", f"{o.expected_wins:.2f} / 9")
m[1].metric("Haftayı kazanma P(5+)", f"{o.p5:.0%}")
m[2].metric("Stratejine göre puan", f"{o.strategy_score:.2f}")
m[3].metric("Sayılan maç (sen / rakip)", f"{o.mine.counted.sum()} / {o.opp.counted.sum()}")
m[4].metric("Yedekte kalan maçın", o.mine.benched, help="O gün aktif slot yetmediği için sayılmayan maçlar")


def category_table(outlook) -> pd.DataFrame:
    tm, to = vector_totals(outlook.mine.vector), vector_totals(outlook.opp.vector)
    labels = [CATEGORY_LABELS[c] for c in CATEGORIES]
    return pd.DataFrame([[tm[c] for c in CATEGORIES], [to[c] for c in CATEGORIES], list(outlook.p)],
                        index=["Sen (beklenen)", "Rakip (beklenen)", "P(kazan)"], columns=labels)


def style_categories(df: pd.DataFrame):
    def css(row):
        if row.name != "P(kazan)":
            return [""] * len(row)
        return [gain_css(v - .5, .35) for v in row]

    fmt = {c: (lambda v: f"{v:.3f}") if c in ("FG%", "FT%") else (lambda v: f"{v:.1f}") for c in df.columns}
    styler = df.style.apply(css, axis=1)
    for c, f in fmt.items():
        styler = styler.format(f, subset=pd.IndexSlice[["Sen (beklenen)", "Rakip (beklenen)"], [c]])
    return styler.format("{:.0%}", subset=pd.IndexSlice[["P(kazan)"], :])


st.dataframe(style_categories(category_table(o)), width="stretch")
swing = [CATEGORY_LABELS[c] for c, p in zip(CATEGORIES, o.p) if .25 <= p <= .75]
st.caption("Çevrilebilir kategoriler (P %25–75): " + (", ".join(swing) or "yok") + ". Beklenen toplamlar şu ana "
           "kadarki skor + kalan günlerde aktif kadroda sayılan maçlardır. Normal yaklaşım; kalibre edilmemiş.")

with st.expander("Gün gün kadron (▶ oynar · B yedekte kalır · ✕ oynamaz)", expanded=True):
    st.dataframe(o.mine.grid.rename(index=names), width="stretch")
with st.expander("Rakibin gün gün kadrosu"):
    st.dataframe(o.opp.grid.rename(index=names), width="stretch")

# ------------------------------------------------------------------- streaming
st.subheader("Streaming planı")
max_acq = acquisition_limit(lg.settings)
s1, s2, s3 = st.columns([1, 1, 3])
used = s1.number_input("Bu hafta kullandığın alım", 0, max_acq, 0, key=f"wk_used_{lg.league_id}_{wk}")
left = max_acq - int(used)
s2.metric("Kalan alım hakkı", left, help=f"Lig ayarı: haftada en fazla {max_acq} alım")
@st.cache_resource(show_spinner=False)
def _drop_order(_eng, fingerprint: str, league_id: str, team: str, strategy) -> list[str]:
    t = drop_ranking(_eng, team, strategy)
    return list(t["drop"]) if len(t) else []


active = model.active_roster(mine)
ranked = [p for p in _drop_order(eng, data.fingerprint, lg.league_id, mine, strategy) if p in active]
default_drop = (ranked or active)[:3]
droppable = s3.multiselect("Bırakılabilecek oyuncular", active, default=default_drop, format_func=lambda p: names[p],
                           key=f"wk_drop_{lg.league_id}_{mine}",
                           help="Varsayılan: kalan sezon için en kolay yerine konan üç oyuncu.")
key = (data.fingerprint, lg.league_id, mine, opp, wk, tuple(days), str(acc_mine), str(acc_opp), strategy,
       out, tuple(droppable), left)
if st.button("Streaming planını hesapla", type="primary", disabled=left <= 0 or not droppable):
    with st.spinner("Boştaki oyuncular gün gün deneniyor…"):
        st.session_state["wk_plan"] = (key, model.stream(o, moves=left, droppable=list(droppable), acc_mine=acc_mine))
plan = st.session_state.get("wk_plan")
if plan and plan[0] == key:
    s = plan[1]
    if not s.moves:
        st.info("Bu haftayı belirgin iyileştiren bir alım bulunamadı (eşik: +0.01 beklenen kategori).")
    else:
        d_ew = s.expected_wins - o.expected_wins
        st.success(f"{len(s.moves)} alımla beklenen kategori {o.expected_wins:.2f} → {s.expected_wins:.2f} "
                   f"({d_ew:+.2f}), haftayı kazanma {o.p5:.0%} → {s.p5:.0%}.")
        st.dataframe(pd.DataFrame([{
            "Gün": f"{mv.day:%a %d.%m}", "Bırak": names[mv.drop], "Al": names[mv.add],
            "Takım": data.players.loc[mv.add, "nba_team"], "Poz": data.players.loc[mv.add, "yahoo_positions"],
            "Bu hafta maçı (o günden)": sum(model.has_game(mv.add, d) for d in s.days if d >= mv.day),
            "Kalıcı olsaydı ROS etkisi": mv.ros_delta} for mv in s.moves])
            .style.format({"Kalıcı olsaydı ROS etkisi": "{:+.3f}"})
            .map(lambda v: gain_css(v, .2), subset=["Kalıcı olsaydı ROS etkisi"]), hide_index=True, width="stretch")
        before = category_table(o).loc["P(kazan)"]
        after = category_table(s).loc["P(kazan)"]
        st.dataframe(pd.DataFrame([before, after, after - before], index=["Önce", "Sonra", "Fark"])
                     .style.format("{:.0%}", subset=pd.IndexSlice[["Önce", "Sonra"], :])
                     .format("{:+.0%}", subset=pd.IndexSlice[["Fark"], :])
                     .map(lambda v: gain_css(v, .3), subset=pd.IndexSlice[["Fark"], :]), width="stretch")
        with st.expander("Plan sonrası gün gün kadron"):
            st.dataframe(s.mine.grid.rename(index=names), width="stretch")
    st.caption("İşlemleri listedeki gün ve sırayla yap: her satırda bırakılan oyuncunun yerine yenisi gelir. Plan "
               "açgözlüdür (her adımda en çok kazandıran alım). Waiver'daki (yeni bırakılmış) oyuncular, Can't Cut "
               "listesi ve maç saatleri doğrulanmadı. 'ROS etkisi', değişiklik kalıcı olsaydı kalan sezona etkisidir; "
               "negatifse o oyuncuyu hafta sonunda geri almayı düşün.")
for note in weeks.notes:
    st.caption(note)
