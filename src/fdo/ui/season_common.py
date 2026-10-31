"""Sezon simülasyonu için ortak Streamlit yardımcıları (Sezon Simülasyonu ve Takas Analizi sayfaları)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from fdo.inseason.fixtures import load_fixtures
from fdo.inseason.season import SeasonResult, SeasonSim
from fdo.inseason.standings import league_standings, load_standings
from fdo.inseason.weekly import WeekModel
from fdo.inseason.weeks import league_weeks
from fdo.trade import TradeEngine
from fdo.ui import trade_common as tc

DEFAULT_SIMS = 2000
SEED = 1
DEFAULT_SD = 0.06          # takım gücü belirsizliği (sezonluk, lognormal sd); Sezon Simülasyonu'ndan değiştirilir


@st.cache_resource(show_spinner="Sezon simülasyonu hazırlanıyor (haftalık kadrolar)…")
def _sim(_eng: TradeEngine, fingerprint: str, league_id: str, utilization: float, data_dir: str) -> SeasonSim | None:
    data, lg = _eng.data, _eng.league
    fixtures = load_fixtures(data_dir)
    if not (fixtures["league_id"] == str(league_id)).any():
        return None
    weeks = league_weeks(data.schedule, lg.settings, lg.config)
    standings = league_standings(load_standings(data_dir), league_id, lg.teams)
    return SeasonSim(WeekModel(_eng), weeks, fixtures, standings, data.as_of)


def season_sim(eng: TradeEngine) -> SeasonSim | None:
    return _sim(eng, eng.data.fingerprint, eng.league.league_id, eng.utilization, str(tc.DATA_DIR))


def run(sim: SeasonSim, eng: TradeEngine, *, rosters=None, n_sims: int = DEFAULT_SIMS, team: str | None = None,
        tag: str = "base") -> SeasonResult:
    """Oturumda önbellekli koşu (aynı seed: senaryolar arasında eşleşmeli fark). Güç belirsizliği oturum ayarı."""
    sd = float(st.session_state.get("season_sd", DEFAULT_SD))
    key = (eng.data.fingerprint, eng.league.league_id, eng.utilization, int(n_sims), team, tag, sd,
           None if rosters is None else tuple(sorted((k, tuple(sorted(v))) for k, v in rosters.items())))
    cache = st.session_state.setdefault("season_runs", {})
    if key not in cache:
        cache[key] = sim.run(rosters, n_sims=n_sims, seed=SEED, team=team, strength_sd=sd)
        while len(cache) > 12:
            cache.pop(next(iter(cache)))
    return cache[key]


def effect_table(eng: TradeEngine, before: SeasonResult, after: SeasonResult, teams) -> pd.DataFrame:
    rows = []
    for t in teams:
        b, a = before.table.loc[t], after.table.loc[t]
        rows.append({"Takım": eng.league.teams[t], "P(playoff) önce": b.p_playoff, "P(playoff) sonra": a.p_playoff,
                     "Δ playoff": a.p_playoff - b.p_playoff, "P(şampiyon) önce": b.p_champion,
                     "P(şampiyon) sonra": a.p_champion, "Δ şampiyon": a.p_champion - b.p_champion,
                     "Ort. sıra önce": b.mean_seed, "Ort. sıra sonra": a.mean_seed})
    return pd.DataFrame(rows)


def show_trade_effect(eng: TradeEngine, result, *, key: str) -> None:
    """Takas Analizi'nde: takasın iki takımın playoff ve şampiyonluk olasılığına etkisi."""
    st.subheader("Playoff ve şampiyonluk etkisi")
    sim = season_sim(eng)
    if sim is None:
        st.caption("Bu lig için fikstür yok; sezon simülasyonu yapılamıyor.")
        return
    n = st.select_slider("Simülasyon", [500, 1000, 2000, 5000], value=DEFAULT_SIMS, key=f"{key}_n")
    if st.button("Sezon etkisini hesapla", key=f"{key}_go"):
        with st.spinner("Kalan sezon ve playoff simüle ediliyor…"):
            base = run(sim, eng, n_sims=n)
            after = run(sim, eng, rosters=result.rosters_after, n_sims=n, tag="trade")
        st.session_state[f"{key}_effect"] = (id(result), n, effect_table(
            eng, base, after, (result.request.team_a, result.request.team_b)))
    saved = st.session_state.get(f"{key}_effect")
    if saved and saved[0] == id(result) and saved[1] == n:
        style_effect(saved[2])
        st.caption("Aynı rastgele çekilişlerle (eşleşmeli) iki senaryo: takassız ve takaslı kadrolar sezon boyu sabit. "
                   "Kalan normal sezon fikstürü ve playoff braketi simüle edilir; kalibre edilmemiş Normal yaklaşım.")


def style_effect(df: pd.DataFrame) -> None:
    from fdo.ui.analysis import gain_css

    pct = [c for c in df.columns if c.startswith("P(") or c.startswith("Δ")]
    st.dataframe(df.style.format({c: "{:+.1%}" if c.startswith("Δ") else "{:.1%}" for c in pct}
                                 | {"Ort. sıra önce": "{:.1f}", "Ort. sıra sonra": "{:.1f}"})
                 .map(lambda v: gain_css(v, .1), subset=["Δ playoff", "Δ şampiyon"]), hide_index=True, width="stretch")


def suggestion_effects(eng: TradeEngine, suggestions, strategy, *, n_sims: int = 1000, progress=None) -> pd.DataFrame:
    """Öneri başına iki takımın ΔP(playoff) ve ΔP(şampiyon) (takassız senaryoya göre, aynı çekilişler)."""
    sim = season_sim(eng)
    if sim is None or not suggestions:
        return pd.DataFrame()
    base = run(sim, eng, n_sims=n_sims)
    rows = []
    for i, s in enumerate(suggestions):
        a, b = s.request.team_a, s.request.team_b
        rosters, _, _ = eng.resolve(s.request, {a: strategy, b: s.other_strategy})
        after = run(sim, eng, rosters=rosters, n_sims=n_sims, tag="suggestion")
        rows.append({"i": i,
                     "me_playoff": after.table.loc[a, "p_playoff"] - base.table.loc[a, "p_playoff"],
                     "me_champion": after.table.loc[a, "p_champion"] - base.table.loc[a, "p_champion"],
                     "opp_playoff": after.table.loc[b, "p_playoff"] - base.table.loc[b, "p_playoff"],
                     "opp_champion": after.table.loc[b, "p_champion"] - base.table.loc[b, "p_champion"]})
        if progress:
            progress(i + 1, len(suggestions))
    return pd.DataFrame(rows).set_index("i")
