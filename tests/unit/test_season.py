"""Sezon simülasyonu: braket, sıralamadan başlama, olasılık toplamları ve CRN."""
from __future__ import annotations

import dataclasses
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from fdo.inseason.season import SeasonSim, bracket_order, playoff_teams
from fdo.inseason.standings import _rows, league_standings
from fdo.inseason.weekly import WeekModel
from fdo.inseason.weeks import league_weeks
from fdo.trade import TradeEngine
from unit.test_inseason import data  # noqa: F401  paylaşılan sentetik lig

ROUND_ROBIN = [(("1", "2"), ("3", "4")), (("1", "3"), ("2", "4")), (("1", "4"), ("2", "3"))]


def _fixtures(weeks) -> pd.DataFrame:
    rows = []
    for w in weeks:
        for a, b in ROUND_ROBIN[w % 3]:
            rows += [{"league_id": "L", "team_id": a, "week": w, "opponent_team_id": b},
                     {"league_id": "L", "team_id": b, "week": w, "opponent_team_id": a}]
    return pd.DataFrame(rows)


@pytest.fixture
def sim(data):  # noqa: F811
    lg = data.leagues["L"]
    lg.settings["Playoffs"] = "2 teams - Week 22 (ends Sunday, Apr 4)"
    eng = TradeEngine(data, "L", utilization=1)
    weeks = league_weeks(data.schedule, lg.settings, lg.config)
    standings = pd.DataFrame({"wins": [7, 2, 5, 4], "losses": [2, 7, 4, 5], "ties": 0},
                             index=["1", "2", "3", "4"])
    return SeasonSim(WeekModel(eng), weeks, _fixtures(range(1, 20)), standings, data.as_of)


def test_bracket_and_settings():
    assert bracket_order(8) == [1, 8, 4, 5, 2, 7, 3, 6] and bracket_order(4) == [1, 4, 2, 3]
    assert playoff_teams({"Playoffs": "6 teams - Week 19, 20 and 21 (ends Sunday, Mar 28)"}) == 6
    assert playoff_teams({}) == 0


def test_standings_rows_from_links_and_table():
    rows = [{"cells": ["1", "A", "7-2-0", ".778"], "links": [{"url": "https://x/nba/93992/7"}]}]
    assert _rows(rows) == [{"league_id": "93992", "team_id": "7", "wins": 7, "losses": 2, "ties": 0}]
    table = {"table": {"rows": [{"cells": ["1", "B", "6-2-1"], "team_id": "4"}]}}
    assert _rows(table, "220594")[0]["ties"] == 1
    df = pd.DataFrame({"league_id": "L", "team_id": ["1", "2"], "wins": 1, "losses": 0, "ties": 0})
    assert league_standings(df, "L", ["1", "2", "3"]) is None and league_standings(df, "L", ["1"]) is not None


def test_season_totals_and_probabilities(sim):
    r = sim.run(n_sims=400, seed=3, team="1")
    t = r.table
    assert r.start_week == 2 and r.playoff_size == 2
    games = 9 * len(sim.regular)
    np.testing.assert_allclose(t["exp_wins"] + t["exp_losses"] + t["exp_ties"], games)
    assert t["p_playoff"].sum() == pytest.approx(2) and t["p_champion"].sum() == pytest.approx(1)
    assert t.loc["1", "p_playoff"] > t.loc["2", "p_playoff"]                   # 7-2 başlayan, 2-7'den önde
    assert t["exp_ties"].sum() > 0                                               # sayım kategorilerinde beraberlik
    assert set(r.schedule["week"]) == set(range(2, 20)) and r.schedule["p_win"].between(0, 1).all()


def test_same_seed_is_reproducible_and_rosters_matter(sim, data):  # noqa: F811
    a = sim.run(n_sims=300, seed=5)
    b = sim.run(n_sims=300, seed=5)
    np.testing.assert_array_equal(a.seeds, b.seeds)
    rosters = dict(data.leagues["L"].rosters)
    strong = rosters["4"]
    rosters["4"], rosters["1"] = rosters["1"], strong                          # kadroları değiştir
    c = sim.run(rosters, n_sims=300, seed=5)
    assert not np.array_equal(a.seeds, c.seeds)


def test_paired_effect_is_zero_for_the_same_rosters_and_carries_an_error(sim, data):  # noqa: F811
    from fdo.inseason.season import paired

    base = sim.run(n_sims=400, seed=4)
    same = sim.run(n_sims=400, seed=4)
    e = sim.effect(base, same, "1")
    assert set(e) == {"playoff", "champion", "seed"}
    assert all(d.delta == 0 and d.se == 0 and not d.clear for d in e.values())      # ortak çekiliş: gürültü yok
    rosters = dict(data.leagues["L"].rosters)
    rosters["4"], rosters["1"] = rosters["1"], rosters["4"]
    after = sim.run(rosters, n_sims=400, seed=4)
    for t in ("1", "4"):
        p = sim.effect(base, after, t)["playoff"]
        assert p.before == pytest.approx(base.table.loc[t, "p_playoff"])
        assert p.after == pytest.approx(after.table.loc[t, "p_playoff"])
        assert p.delta == pytest.approx(p.after - p.before) and p.se > 0
    with pytest.raises(ValueError):
        sim.effect(base, sim.run(n_sims=200, seed=4), "1")
    d = paired(np.array([0, 0, 1, 1]), np.array([1, 1, 1, 1]))
    assert d.delta == .5 and d.se == pytest.approx(np.std([1, 1, 0, 0], ddof=1) / 2)


def test_strength_uncertainty_softens_extremes(sim):
    sharp = sim.run(n_sims=600, seed=2, strength_sd=0.0).table
    soft = sim.run(n_sims=600, seed=2, strength_sd=0.5).table
    share = 2 / 4
    assert soft["p_playoff"].sum() == pytest.approx(2) and soft["p_champion"].sum() == pytest.approx(1)
    assert (soft["p_playoff"] - share).abs().mean() <= (sharp["p_playoff"] - share).abs().mean() + 1e-9


def test_fixture_outlook_matches_the_simulated_schedule(sim):
    res = sim.run(n_sims=50, seed=3, team="1")
    pd.testing.assert_frame_equal(res.schedule.reset_index(drop=True), sim.fixture_outlook("1"))
    assert len(res.schedule) and res.schedule["p_win"].between(0, 1).all()


def test_returning_il_player_pushes_the_weakest_active_off_the_roster(sim):
    from fdo.inseason.weekly import Stint
    from fdo.trade.strategy import Strategy
    eng = sim.engine
    roster, il = ("4", "5", "6", "7", "16"), frozenset({"7"})        # 4 aktif = kapasite, 7 IL'de
    gone = sim.drop_schedule(roster, il)
    u = eng._utility_array(Strategy())
    worst = min(roster, key=lambda p: u[eng.index[p]])
    assert gone == {worst: sim.as_of + dt.timedelta(days=7)}       # dönüş tarihi bilinmiyor → gelecek hafta
    days = sim.weeks.days(3)                                         # dönüş haftası (2–8 Kasım)
    last = sum(d < gone[worst] for d in days) - 1
    stints = [Stint(p, last=last if p == worst else 10_000, slot=k) for k, p in enumerate(roster)
              if not (p == worst and last < 0)]
    expected = sim.model.team_week("2", stints, days, use_status=False).vector
    np.testing.assert_allclose(sim.vector("2", roster, 3, il), expected)


def test_current_week_trade_changes_only_the_remaining_days(data):  # noqa: F811
    # 2. hafta (26 Ekim – 1 Kasım) veri tarihinde (31 Ekim) sürüyor: AAA yalnız geçmişte, BBB yalnız kalan günde oynar.
    extra = pd.DataFrame([{"game_date": "2026-10-28", "home_team": "AAA", "away_team": "CCC"},
                          {"game_date": "2026-11-01", "home_team": "BBB", "away_team": "DDD"}])
    data = dataclasses.replace(data, schedule=pd.concat([data.schedule, extra], ignore_index=True))
    lg = data.leagues["L"]
    eng = TradeEngine(data, "L", utilization=1)
    s = SeasonSim(WeekModel(eng), league_weeks(data.schedule, lg.settings, lg.config), _fixtures(range(1, 20)),
                  pd.DataFrame({"wins": [7, 2, 5, 4], "losses": [2, 7, 4, 5], "ties": 0}, index=["1", "2", "3", "4"]),
                  data.as_of)
    w = s.current_week
    assert w == 2 and min(s.weeks.days(w)) < data.as_of <= max(s.weeks.days(w))
    roster = lg.rosters["1"]                                          # 0 AAA, 1 BBB, 2 CCC (O), 3 DDD
    swap = lambda out, inn: tuple(p for p in roster if p != out) + (inn,)
    base = s.vector("1", roster, w)
    np.testing.assert_allclose(s.vector("1", swap("0", "16"), w), base)       # AAA'nın maçı geçti: takas etkilemez
    assert not np.allclose(s.vector("1", swap("1", "17"), w), base)          # BBB kalan günde oynar
    assert s._past("1", w)[1] > 0 and any("hafta sürüyor" in n for n in s.notes)


def test_current_week_past_days_use_the_realized_totals(data):  # noqa: F811
    from fdo.inseason.weekly import accumulated_vector

    lg = data.leagues["L"]
    eng = TradeEngine(data, "L", utilization=1)
    weeks = league_weeks(data.schedule, lg.settings, lg.config)
    standings = pd.DataFrame({"wins": [7, 2, 5, 4], "losses": [2, 7, 4, 5], "ties": 0}, index=["1", "2", "3", "4"])
    totals = {t: {"fgm": 40, "fga": 90, "ftm": 20, "fta": 25, "fg3m": 9, "pts": 130 + i, "reb": 50, "ast": 30,
                  "stl": 8, "blk": 5, "tov": 15} for i, t in enumerate(["1", "2", "3", "4"])}
    s = SeasonSim(WeekModel(eng), weeks, _fixtures(range(1, 20)), standings, data.as_of, realized=totals)
    w = s.current_week
    np.testing.assert_allclose(s._past("2", w), accumulated_vector(totals["2"]))
    roster = lg.rosters["1"]
    future = s.vector("1", roster, w) - s._past("1", w)                       # kalan günler + gerçek toplam
    assert future[1] < s.vector("1", roster, w)[1] and any("gerçek skor" in n for n in s.notes)
    # bir takımın toplamı eksikse gerçek skor kullanılmaz (takımlar arasında karışık taban olmasın)
    partial = SeasonSim(WeekModel(eng), weeks, _fixtures(range(1, 20)), standings, data.as_of,
                        realized={k: v for k, v in totals.items() if k != "4"})
    assert not np.allclose(partial._past("2", w), accumulated_vector(totals["2"]))
    assert any("bilinmediği" in n for n in partial.notes)


def test_playoff_tie_on_categories_goes_to_the_higher_seed(sim, monkeypatch):
    # bütün kategoriler berabere: her turu üst sıradaki kazanır → şampiyon hep 1. sıra
    monkeypatch.setattr(sim, "_outcomes", lambda a, b, rng: (np.zeros(a.shape[:-1], int), np.full(a.shape[:-1], 9)))
    r = sim.run(n_sims=50, seed=1)
    first = r.seeds.argmin(axis=1)
    assert r.champion[np.arange(50), first].all() and r.table["exp_ties"].min() > 0


def test_waiver_moves_take_free_agents_in_order_and_cancel_out_without_a_trade(data):  # noqa: F811
    lg = data.leagues["L"]
    lg.settings["Playoffs"] = "2 teams - Week 22 (ends Sunday, Apr 4)"
    eng = TradeEngine(data, "L", utilization=1)
    weeks = league_weeks(data.schedule, lg.settings, lg.config)
    st = pd.DataFrame({"wins": [7, 2, 5, 4], "losses": [2, 7, 4, 5], "ties": 0}, index=["1", "2", "3", "4"])
    plain = SeasonSim(WeekModel(eng), weeks, _fixtures(range(1, 20)), st, data.as_of)
    sim = SeasonSim(WeekModel(eng), weeks, _fixtures(range(1, 20)), st, data.as_of, waiver_order=("2", "1"))
    assert plain.with_waivers(dict(lg.rosters)) == dict(lg.rosters)
    moved = sim.with_waivers(dict(lg.rosters))
    fa = set(eng.free_agents)
    got = {t: set(moved[t]) & fa for t in moved}
    assert got["2"] and not got["3"] and not got["4"]                       # yalnız sıradakiler
    assert not got["1"] & got["2"]                                          # ortak havuz: aynı oyuncu iki takıma gitmez
    first = sim.with_waivers(dict(lg.rosters), first=("1",))
    best = eng._fa_order(eng.free_agents and __import__("fdo.trade.strategy", fromlist=["Strategy"]).Strategy())[0]
    assert best in first["1"]                                               # önce hareket eden en iyisini alır
    a = sim.run(n_sims=200, seed=2, first=("1", "2"))
    b = sim.run(dict(lg.rosters), n_sims=200, seed=2, first=("1", "2"))
    assert all(d.delta == 0 for d in sim.effect(a, b, "1").values())
