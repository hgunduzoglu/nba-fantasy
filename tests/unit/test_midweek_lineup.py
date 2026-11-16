"""Accumulated scores and remaining production must share one weekly horizon."""
import datetime as dt

import numpy as np

from fdo.inseason.season import SeasonSim
from fdo.inseason.weekly import Stint, accumulated_vector
from fdo.inseason.weeks import league_weeks
from fdo.trade import Strategy
from unit.test_review_regressions import _one_slot_model
from unit.test_trade import trade_data  # noqa: F401
from unit.test_season import _fixtures


PTS = Strategy("PTS", (0, 0, 0, 1, 0, 0, 0, 0, 0))


def test_midweek_outlook_chooses_points_against_the_opponents_complete_week(trade_data):
    model, day = _one_slot_model(trade_data)
    model.strategy = PTS
    model.unit[0, 1], model.unit[1, 1], model.unit[3, 1] = 10, 20, 10
    out = model.outlook("1", "2", [day], acc_mine={"pts": 200}, acc_opp={"pts": 205})
    assert out.mine.counted["1"] == 1 and out.mine.counted["0"] == 0
    assert out.mine.vector[1] == 220 and out.opp.vector[1] == 215 and out.p[3] == 1


def test_midweek_ratio_selection_uses_actual_opponent_shooting_totals(trade_data):
    model, day = _one_slot_model(trade_data)
    model.strategy = Strategy("FG%", (1, 0, 0, 0, 0, 0, 0, 0, 0))
    model.lineup_reference = accumulated_vector({"fgm": 1, "fga": 2})
    model.unit[0, 14:16], model.unit[1, 14:16] = [1, 10], [6, 10]
    out = model.outlook("1", "2", [day], acc_mine={"fgm": 45, "fga": 100}, acc_opp={"fgm": 44, "fga": 100})
    assert out.mine.counted["1"] == 1 and out.mine.vector[14] / out.mine.vector[15] > .44
    assert out.p[0] == 1


def test_today_selection_includes_the_rest_of_the_weeks_lineup(trade_data):
    model, day = _one_slot_model(trade_data)
    later = day + dt.timedelta(days=1)
    model.games[later] = {"SYN"}
    model.strategy = Strategy("PTS/AST", (0, 0, 0, 1, 0, 1, 0, 0, 0))
    model.lineup_reference = accumulated_vector({"pts": 100, "ast": 5})
    model.unit[0, 1], model.unit[1, 3], model.unit[2, 3] = 20, 10, 20
    stints = [Stint("0", last=0), Stint("1", last=0), Stint("2", first=1)]
    out = model.team_week("1", stints, [day, later], reference=accumulated_vector({"pts": 10, "ast": 15}))
    assert out.counted["0"] == out.counted["2"] == 1 and out.counted["1"] == 0
    assert out.vector[1] == 20 and out.vector[3] == 20


def test_season_selection_sees_actual_past_scores_before_choosing_lineup(trade_data):
    model, day = _one_slot_model(trade_data)
    model.unit[0, 1], model.unit[1, 1] = 10, 20
    model.lineup_reference = accumulated_vector({"pts": 5})
    cfg = trade_data.leagues["L"].config
    weeks = league_weeks(trade_data.schedule, {}, cfg)
    realized = {t: {"pts": 200 if t == "1" else 205} for t in model.engine.team_ids}
    sim = SeasonSim(model, weeks, _fixtures(range(1, 5)), None, day, realized=realized)
    out = sim.vector("1", ("0", "1"), sim.current_week, strategy=PTS)
    assert out[1] == 220
    np.testing.assert_array_equal(out, sim.vector("1", ("0", "1"), sim.current_week, strategy=PTS))
