"""Takas değerlendirmesinin istatistik temelleri ve IL dönüş planı (README §13.28)."""
import dataclasses

import numpy as np
import pandas as pd
import pytest

from fdo.inseason.scenarios import basis_data, basis_rates
from fdo.trade.data import ROS
from fdo.trade.engine import TradeEngine
from unit.test_inseason import TEAMS, data  # noqa: F401  paylaşılan sentetik lig


def test_season_and_blend_change_rates_but_keep_remaining_games(data):  # noqa: F811
    ros = data.stats[ROS]
    data.stats["season_total"].loc["0", "pts"] = ros.loc["0", "pts"] * 2      # bu sezon iki kat sayı (10 maç)
    s = basis_rates(data, "season")
    assert s.loc["0", "pts"] == pytest.approx(ros.loc["0", "pts"] * 2) and s.loc["0", "gp"] == ros.loc["0", "gp"]
    b = basis_rates(data, "blend")                                            # 10 maç → yarı yarıya
    assert b.loc["0", "pts"] == pytest.approx(ros.loc["0", "pts"] * 1.5)
    assert basis_rates(data, "ros") is ros and basis_data(data, "ros") is data
    assert basis_data(data, "season").fingerprint != data.fingerprint
    with pytest.raises(ValueError):
        basis_rates(data, "uydurma")


def test_few_games_fall_back_to_projection(data):  # noqa: F811
    data.stats["season_total"].loc["1", ["gp", "pts"]] = [2.0, 999.0]
    assert basis_rates(data, "season").loc["1", "pts"] == data.stats[ROS].loc["1", "pts"]
    assert basis_rates(data, "blend").loc["1", "pts"] == pytest.approx(data.stats[ROS].loc["1", "pts"])


def test_recent_uses_last_games_from_logs(data):  # noqa: F811
    stats = {"fgm": 8, "fga": 16, "ftm": 4, "fta": 5, "fg3m": 2, "pts": 30, "reb": 5, "ast": 4, "stl": 1, "blk": 1,
             "tov": 2}
    logs = pd.DataFrame([{"name": "P0", "nba_team": TEAMS[0], "game_date": f"2026-11-0{i}", "minutes": 30, **stats}
                         for i in range(1, 6)])
    r = basis_rates(data, "recent", logs)
    assert r.loc["0", "pts"] == pytest.approx(30 * data.stats[ROS].loc["0", "gp"])
    assert r.loc["2", "pts"] == pytest.approx(basis_rates(data, "season").loc["2", "pts"])     # kaydı yok


def test_crunch_plan_matches_crunch_vector(data):  # noqa: F811
    lg = data.leagues["L"]
    data.leagues["L"] = dataclasses.replace(lg, rosters={**lg.rosters, "1": lg.rosters["1"] + ("16",)},
                                            injury_rosters={**lg.injury_rosters, "1": frozenset({"16"})})
    eng = TradeEngine(data, "L", utilization=1)
    roster, il = eng.league.rosters["1"], eng.league.injury_rosters["1"]
    plan = eng.crunch_plan(roster, il)
    assert len(plan) == 1 and plan[0][0] == "16" and plan[0][1] is not None      # kadro dolu: biri bırakılır
    r, d = plan[0]
    expected = eng.vecs[eng.index[r]] if d == r else eng.return_share(r) * eng.vecs[eng.index[d]]
    assert np.allclose(eng.crunch_vector(roster, il), expected)
    free = eng.crunch_plan(eng.league.rosters["2"], eng.league.injury_rosters["2"])
    assert free == [("7", None)]                                                  # boş yer var: kimse gitmez
