"""Sezon simülasyonu: braket, sıralamadan başlama, olasılık toplamları ve CRN."""
from __future__ import annotations

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
