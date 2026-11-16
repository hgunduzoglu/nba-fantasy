"""Sezon içi: lig hafta takvimi, fikstür, haftalık eşleşme, streaming ve boştaki oyuncular."""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from fdo.config import load_config
from fdo.inseason.fixtures import load_fixtures, opponent
from fdo.inseason.waiver import drop_candidates, free_agents, swap_delta, waiver_table
from fdo.inseason.weekly import WeekModel, accumulated_vector
from fdo.inseason.weeks import league_weeks, parse_playoffs
from fdo.matchup.ecw import p_win
from fdo.trade import Strategy, TradeData, TradeEngine, TradeLeague
from fdo.trade.data import MODES

TEAMS = ("AAA", "BBB", "CCC", "DDD")
WEEK3 = [dt.date(2026, 11, 2) + dt.timedelta(days=i) for i in range(7)]


def _schedule() -> pd.DataFrame:
    rows = []
    for i, day in enumerate(WEEK3):
        home, away = TEAMS[i % 4], TEAMS[(i + 1) % 4]
        rows.append({"game_date": day.isoformat(), "home_team": home, "away_team": away})
        if i % 2 == 0:
            rows.append({"game_date": day.isoformat(), "home_team": TEAMS[(i + 2) % 4], "away_team": TEAMS[(i + 3) % 4]})
    rows += [{"game_date": "2026-10-20", "home_team": "AAA", "away_team": "BBB"},
             {"game_date": "2027-04-11", "home_team": "CCC", "away_team": "DDD"}]
    return pd.DataFrame(rows)


@pytest.fixture
def data() -> TradeData:
    cfg = load_config()
    slots = {s: 0 for s in cfg.roster.slots}
    slots.update(PG=1, C=1, BN=2)
    mix = {k: 0 for k in cfg.model.bots.mix}
    mix["MarketFollower"] = 3
    cfg = cfg.with_overrides({"league": {"teams": 4, "my_seat": 1, "rounds": 4},
                              "roster": {"slots": slots, "active_slots": ["PG", "C"]},
                              "model": {"bots": {"mix": mix}}, "unverified": {"il_slots": 1}})
    rng = np.random.default_rng(7)
    ids = [str(i) for i in range(30)]
    fga = rng.uniform(60, 220, len(ids))
    fgm = fga * rng.uniform(.35, .65, len(ids))
    fta = rng.uniform(10, 100, len(ids))
    ftm = fta * rng.uniform(.55, .95, len(ids))
    fg3 = np.minimum(fgm, rng.uniform(0, 40, len(ids)))
    frame = pd.DataFrame({"gp": 10., "fgm": fgm, "fga": fga, "ftm": ftm, "fta": fta, "fg3m": fg3,
                          "pts": 2 * fgm + ftm + fg3, "reb": rng.uniform(15, 120, len(ids)),
                          "ast": rng.uniform(10, 100, len(ids)), "stl": rng.uniform(1, 20, len(ids)),
                          "blk": rng.uniform(1, 20, len(ids)), "tov": rng.uniform(5, 40, len(ids))}, index=ids)
    players = pd.DataFrame({"name": [f"P{i}" for i in ids], "nba_team": [TEAMS[i % 4] for i in range(len(ids))],
                            "yahoo_positions": ["PG" if i % 2 else "C" for i in range(len(ids))],
                            "injury_status": ""}, index=ids)
    players.loc["2", "injury_status"] = "O"
    rosters = {str(t): tuple(ids[(t - 1) * 4:t * 4]) for t in range(1, 5)}         # 0..15 kadrolu, 16..29 boşta
    injury = {t: frozenset() for t in rosters}
    injury["2"] = frozenset({"7"})
    settings = {"Trade End Date": "March 4, 2027", "Playoffs": "8 teams - Week 20, 21 and 22 (ends Sunday, Apr 4)",
                "Max Acquisitions per Week": "4"}
    league = TradeLeague("L", "Test", {t: f"Takım {t}" for t in rosters}, rosters, injury, settings, cfg, "1",
                         dt.date(2026, 10, 31))
    return TradeData({"L": league}, players, {m: frame.copy(deep=True) for m in MODES},
                     {m: {"kind": m} for m in MODES}, None, _schedule(), league.roster_date, "t", ())


@pytest.fixture
def eng(data):
    return TradeEngine(data, "L", utilization=1)


def test_league_weeks_from_settings():
    cfg = load_config()
    sched = pd.DataFrame({"game_date": ["2026-10-20", "2027-04-11"], "home_team": "A", "away_team": "B"})
    w = league_weeks(sched, {"Playoffs": "8 teams - Week 20, 21 and 22 (ends Sunday, Apr 4)"}, cfg)
    assert w.week_of(dt.date(2026, 10, 31)) == 2 and w.weeks.loc[1, "start"] == dt.date(2026, 10, 20)
    assert w.weeks.loc[1, "end"] == dt.date(2026, 10, 25) and w.weeks.loc[18, "n_days"] == 14
    assert w.weeks.loc[22, "end"] == dt.date(2027, 4, 4) and w.weeks.index.max() == 22 and w.notes
    assert w.playoff_weeks == (20, 21, 22) and w.weeks["playoff"].sum() == 3
    assert w.days(2, dt.date(2026, 10, 31)) == [dt.date(2026, 10, 31), dt.date(2026, 11, 1)]
    assert parse_playoffs("6 teams - Week 19, 20 and 21 (ends Sunday, Mar 28)", dt.date(2026, 10, 20)) == \
        ((19, 20, 21), dt.date(2027, 3, 28))


def test_fixtures_are_mirrored(tmp_path):
    pd.DataFrame({"league_id": ["L", "L"], "team_id": ["1", "1"], "week": [1, 2],
                  "opponent_team_id": ["3", "4"], "opponent_name": ["x", "y"]}).to_csv(tmp_path / "fixtures_partial.csv",
                                                                                        index=False)
    f = load_fixtures(tmp_path)
    assert opponent(f, "L", "1", 2) == "4" and opponent(f, "L", "4", 2) == "1" and opponent(f, "L", "2", 1) is None


def test_accumulated_vector_is_deterministic(data):
    cfg = data.leagues["L"].config
    a = accumulated_vector({"fgm": 50, "fga": 100, "ftm": 8, "fta": 10, "fg3m": 9, "pts": 120, "reb": 40,
                            "ast": 20, "stl": 5, "blk": 3, "tov": 10})
    b = accumulated_vector({"fgm": 40, "fga": 100, "ftm": 9, "fta": 10, "fg3m": 9, "pts": 130, "reb": 30,
                            "ast": 25, "stl": 5, "blk": 4, "tov": 12})
    p = p_win(a, b, cfg)
    # FG% kazanır, FT% kaybeder, 3PM berabere, PTS kaybeder, REB kazanır, AST kaybeder, STL berabere, BLK kaybeder, TO kazanır
    np.testing.assert_allclose(p, [1, 0, .5, 0, 1, 0, .5, 0, 1])


def test_outlook_respects_slots_injuries_and_il(eng, data):
    m = WeekModel(eng)
    o = m.outlook("1", "2", WEEK3, week=3)
    grid = o.mine.grid
    assert ((grid == "▶").sum(axis=0) <= 2).all()                            # 2 aktif slot (PG, C)
    assert "✕" in set(grid.loc["2"]) or (grid.loc["2"] == "").all()          # O durumlu oyuncu oynamaz
    assert o.mine.counted["2"] == 0 and "7" not in o.opp.grid.index         # IL'deki oyuncu kadro dışı
    assert 0 <= o.p5 <= 1 and o.expected_wins == pytest.approx(o.p.sum())
    acc = {"pts": 500}
    assert m.outlook("1", "2", WEEK3, acc_mine=acc).p[3] > o.p[3]


def test_stream_keeps_roster_size_and_chains(eng):
    m = WeekModel(eng)
    base = m.outlook("1", "2", WEEK3, week=3)
    droppable = ["0", "1"]
    s = m.stream(base, moves=3, droppable=droppable, min_gain=0.0)
    assert len(s.moves) <= 3 and s.strategy_score >= base.strategy_score - 1e-9
    n = len(base.mine.stints)
    for d in range(len(WEEK3)):
        assert sum(st.first <= d <= st.last for st in s.mine.stints) == n
    assert all(mv.drop in droppable or mv.drop in {x.add for x in s.moves} for mv in s.moves)
    assert [mv.day for mv in s.moves] == sorted(mv.day for mv in s.moves)
    fa = set(free_agents(eng))
    assert all(mv.add in fa for mv in s.moves)


def test_beam_stream_is_never_worse_than_greedy_and_keeps_the_roster(eng):
    m = WeekModel(eng)
    base = m.outlook("1", "2", WEEK3, week=3)
    greedy = m.stream(base, moves=2, droppable=["0"], min_gain=0.0, shortlist=8)
    wide = m.stream(base, moves=2, droppable=["0"], min_gain=0.0, shortlist=8, beam=2)
    assert wide.strategy_score >= greedy.strategy_score - 1e-9 and len(wide.moves) <= 2
    n = len(base.mine.stints)
    for d in range(len(WEEK3)):
        assert sum(st.first <= d <= st.last for st in wide.mine.stints) == n


def test_waiver_table_matches_swap_delta(eng):
    s = Strategy.preset("Punt FT_PCT")
    t = waiver_table(eng, "2", s)
    assert len(t) and "7" not in set(t["drop"]) and "7" not in drop_candidates(eng, "2")
    row = t.iloc[0]
    assert row["score"] == pytest.approx(swap_delta(eng, "2", row["drop"], row["add"], s))
    assert row["score"] == pytest.approx(9 * sum(row[f"d_{c}"] * w for c, w in
                                                 zip(("FG_PCT", "FT_PCT", "FG3M", "PTS", "REB", "AST", "STL", "BLK",
                                                      "TOV"), s.normalized)))
    assert t["score"].is_monotonic_decreasing


def test_real_default_team_is_user_flag():
    import json

    from fdo.config import REPO_ROOT
    from fdo.trade import load_trade_data

    info = REPO_ROOT / "data/real/league_info.json"
    if not info.exists():
        pytest.skip("Kişisel veri snapshot'ı yok")
    flagged = {str(lg["league_id"]): [str(t["team_id"]) for t in lg.get("schedules", {}).get("teams", [])
                                      if str(t.get("is_user_team")).lower() == "true"]
               for lg in json.loads(info.read_text(encoding="utf-8-sig"))["leagues"]}
    d = load_trade_data()
    for lid, lg in d.leagues.items():
        if flagged.get(lid):
            assert lg.default_team_id == flagged[lid][0]


def test_back_to_back_second_games_weigh_less_and_keep_the_expected_total(data):
    import dataclasses
    from fdo.inseason.injuries import apply_injuries
    plain = WeekModel(TradeEngine(data, "L", utilization=1), questionable=1.0, b2b={})
    d = dataclasses.replace(data, sources={**data.sources, "attendance": {"b2b": {"healthy": .8}}})
    m = WeekModel(TradeEngine(d, "L", utilization=1), questionable=1.0)
    w = m.play_weight["0"]
    team = m.team[m.engine.index["0"]]
    days = sorted(w)
    second = [x for x in days if team in m.games.get(x - dt.timedelta(days=1), set())]
    assert second and all(w[x] < 1 for x in second) and all(w[x] > 1 for x in days if x not in second)
    assert sum(w.values()) == pytest.approx(len(days))                  # beklenen maç toplamı aynı
    assert "0" not in plain.play_weight
    # dönüşten sonraki pencere: yalnız dönüş tarihi bilinen oyuncuda, kendi oranıyla
    inj = pd.DataFrame([{"player_id": "1", "kind": "out_until", "return_date": dt.date(2026, 11, 3)}]).set_index("player_id")
    d2 = apply_injuries(data, inj, pmf={0: 1.0})
    d2 = dataclasses.replace(d2, sources={**d2.sources, "attendance": {"b2b": {"healthy": 1.0, "after_return": {14: .5}}}})
    m2 = WeekModel(TradeEngine(d2, "L", utilization=1), questionable=1.0)
    w2, team2 = m2.play_weight["1"], m2.team[m2.engine.index["1"]]
    after = [x for x in w2 if team2 in m2.games.get(x - dt.timedelta(days=1), set()) and x > dt.date(2026, 11, 3)]
    assert after and all(w2[x] < 1 for x in after)
    assert "0" not in m2.play_weight                                  # sağlıklı oran 1: dokunulmaz


def test_b2b_play_rates_measure_second_games_against_other_games():
    from fdo.inseason.returns import b2b_play_rates
    rows = []
    days = [dt.date(2026, 11, 1) + dt.timedelta(days=i) for i in range(120) if i % 3 != 2]   # her iki maçtan biri B2B
    for team in ("AAA", "BBB"):
        for k in range(3):
            name = f"{team}{k}"
            for j, day in enumerate(days):
                b2b2 = day - dt.timedelta(days=1) in days
                if b2b2 and j % 4 == 1 and k < 2:          # ikisi B2B ikinci maçlarının yarısını atlar, biri hep oynar
                    continue
                rows.append({"name": name, "nba_team": team, "game_date": day, "minutes": 30.0})
    out = b2b_play_rates([pd.DataFrame(rows)])
    assert out["healthy"] == pytest.approx(2 / 3, abs=.05) and out["n"]["healthy"] >= 30
    assert out["after_return"] == {}
    assert b2b_play_rates([pd.DataFrame(columns=["name", "nba_team", "game_date", "minutes"])]) == {"after_return": {}, "n": {}}


def test_questionable_and_return_distribution_weight_the_games(data):
    import dataclasses
    from fdo.inseason.injuries import apply_injuries
    from fdo.inseason.weekly import Stint
    from fdo.matchup.player_week import attendance_vectors
    data.players.loc["0", "injury_status"] = "Q"
    eng = TradeEngine(data, "L", utilization=1)
    stints = [Stint("0")]
    full = WeekModel(eng, questionable=1.0, b2b={}).team_week("1", stints, WEEK3)
    half = WeekModel(eng, questionable=.5, b2b={}).team_week("1", stints, WEEK3)
    m = WeekModel(eng, questionable=.5, b2b={})
    i, nxt = eng.index["0"], min(d for d in WEEK3 if m.has_game("0", d))
    assert m.play_weight["0"] == {nxt: .5}
    assert half.slots[WEEK3.index(nxt), 0] >= 0
    expected = attendance_vectors(m.unit[i], m.availability[i]) - attendance_vectors(m.unit[i], .5 * m.availability[i])
    np.testing.assert_allclose(full.vector - half.vector, expected, atol=1e-10)
    # dönüş dağılımı: dönüşten sonraki maçlar dönmüş olma olasılığıyla, beklenen maç kadar
    inj = pd.DataFrame([{"player_id": "1", "kind": "out_until", "return_date": dt.date(2026, 11, 3)}]).set_index("player_id")
    d = apply_injuries(data, inj, pmf={0: .5, 1: .5})
    assert d.sources["injuries"]["delay_pmf"] == {0: .5, 1: .5}
    wm = WeekModel(TradeEngine(d, "L", utilization=1), questionable=1.0, b2b={})
    w = wm.play_weight["1"]
    first = sorted(w)
    assert w[first[0]] == pytest.approx(.5) and all(w[x] == pytest.approx(1) for x in first[1:])
