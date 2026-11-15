"""Budget, attendance and replay regressions from the November review."""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import replace

import numpy as np
import pytest

from fdo.config import REPO_ROOT
from fdo.api.state import AppState
from fdo.evaluation.forward import freeze_model, replay_model, snapshot_dir
from fdo.inseason.lineup_rank import LineupDelta, final_decision, ranked_method
from fdo.inseason.weekly import Stint, WeekModel
from fdo.inseason.season import SeasonSim
from fdo.inseason.weeks import league_weeks
from fdo.matchup.player_week import attendance_vectors, ratio_mean_var
from fdo.trade import Strategy, TradeEngine, TradeError, TradeRequest
from fdo.trade.suggest import Suggestion
from unit.test_trade import trade_data  # noqa: F401
from unit.test_season import _fixtures


def test_exhausted_auto_fill_does_not_put_a_free_agent_in_this_weeks_roster(trade_data):
    eng = TradeEngine(trade_data, "L", adds_used={"1": 1}, adds_limit=1)
    req = TradeRequest("1", "2", ("0", "1"), ("3",), auto_drop=True, auto_fill=True)
    rosters, adj, il = eng.resolve(req)
    assert set(rosters["1"]) == {"2", "3"} and not adj["1"]["add"]
    plan = eng.waiver_plans(rosters, {"1": Strategy(), "2": Strategy()}, il)["1"]
    assert set(plan.week_roster) == {"2", "3"}


def test_explicit_adds_and_auto_fill_and_optional_moves_share_the_limit(trade_data):
    eng = TradeEngine(trade_data, "L", adds_used={"1": 0}, adds_limit=1)
    req = TradeRequest("1", "2", ("0", "1"), ("3",), add_a=("12",), auto_drop=True, auto_fill=True)
    rosters, adj, il = eng.resolve(req)
    assert adj["1"]["add"] == ("12",)
    plan = eng.waiver_plans(rosters, {"1": Strategy(), "2": Strategy()}, il)["1"]
    assert len(plan.moves) == 1 and plan.moves[0] == (None, "12")
    assert "12" in plan.week_roster
    spent = TradeEngine(trade_data, "L", adds_used={"1": 1}, adds_limit=1)
    with pytest.raises(TradeError, match="alım hakkı"):
        spent.resolve(req)


def test_known_waiver_date_is_checked_before_manual_or_auto_add(trade_data):
    future = trade_data.as_of + dt.timedelta(days=3)
    eng = TradeEngine(trade_data, "L", available_from={str(p): future for p in range(12, 20)})
    req = TradeRequest("1", "2", ("0", "1"), ("3",), auto_drop=True, auto_fill=True)
    _, adj, _ = eng.resolve(req)
    assert not adj["1"]["add"]
    with pytest.raises(TradeError, match="waiver"):
        eng.resolve(replace(req, add_a=("12",)))
    assert not eng.waiver_best(("2", "3"))[1]


def test_attendance_includes_the_bernoulli_variance_and_shooting_covariance():
    unit = np.zeros(24)
    unit[1], unit[8] = 30, 36
    unit[14:19] = [5, 10, 4, 3, 9]
    v = attendance_vectors(unit, .5)
    assert v[1] == 15 and v[8] == 243
    assert v[16] == .5 * 4 + .25 * 25
    assert v[17] == .5 * 3 + .25 * 50
    assert v[18] == .5 * 9 + .25 * 100
    _, variance = ratio_mean_var(v, "fg", .4)
    _, conditional = ratio_mean_var(unit, "fg", .4)
    assert variance == pytest.approx(.5 * conditional + .25 * (5 - .4 * 10) ** 2)
    np.testing.assert_array_equal(attendance_vectors(unit, 1), unit)
    np.testing.assert_array_equal(attendance_vectors(unit, 0), np.zeros(24))


def _one_slot_model(trade_data):
    lg = trade_data.leagues["L"]
    slots = {s: 0 for s in lg.config.roster.slots}
    slots.update(UTIL=1, BN=2)
    cfg = lg.config.with_overrides({"roster": {"slots": slots, "active_slots": ["UTIL"]}})
    trade_data.leagues["L"] = replace(lg, config=cfg)
    model = WeekModel(TradeEngine(trade_data, "L"), questionable=1)
    model.unit = np.zeros_like(model.unit)
    model.boost_unit[:] = 0
    model.availability[:] = 1
    day = trade_data.as_of
    model.games[day] = {"SYN"}
    return model, day


def test_lineup_prefers_20_healthy_points_to_30_at_half_probability(trade_data):
    model, day = _one_slot_model(trade_data)
    model.unit[0, 1], model.unit[1, 1] = 30, 20
    model.play_weight["0"] = {day: .5}
    pts = Strategy("PTS", (0, 0, 0, 1, 0, 0, 0, 0, 0))
    week = model.team_week("1", [Stint("0"), Stint("1")], [day], strategy=pts)
    assert week.counted["0"] == 0 and week.counted["1"] == 1 and week.vector[1] == 20


def test_lineup_strategy_changes_the_players_selected_before_scoring(trade_data):
    model, day = _one_slot_model(trade_data)
    model.unit[0, 1], model.unit[1, 2] = 30, 20
    players = [Stint("0"), Stint("1")]
    pts = Strategy("PTS", (0, 0, 0, 1, 0, 0, 0, 0, 0))
    reb = Strategy("REB", (0, 0, 0, 0, 1, 0, 0, 0, 0))
    assert model.team_week("1", players, [day], strategy=pts).counted["0"] == 1
    assert model.team_week("1", players, [day], strategy=reb).counted["1"] == 1


def test_season_lineup_and_cache_are_keyed_by_the_teams_strategy(trade_data):
    model, day = _one_slot_model(trade_data)
    model.unit[0, 1], model.unit[1, 2] = 30, 20
    cfg = trade_data.leagues["L"].config
    weeks = league_weeks(trade_data.schedule, {}, cfg)
    sim = SeasonSim(model, weeks, _fixtures(range(1, 5)), None, day)
    pts = Strategy("PTS", (0, 0, 0, 1, 0, 0, 0, 0, 0))
    reb = Strategy("REB", (0, 0, 0, 0, 1, 0, 0, 0, 0))
    a = sim.vector("1", ("0", "1"), sim.current_week, strategy=pts)
    b = sim.vector("1", ("0", "1"), sim.current_week, strategy=reb)
    assert a[1] == 30 and a[2] == 0
    assert b[1] == 0 and b[2] == 20
    np.testing.assert_array_equal(sim.vector("1", ("0", "1"), sim.current_week, strategy=pts), a)


def test_final_classification_uses_both_teams_and_reports_fallback():
    s = Suggestion(TradeRequest("1", "2", ("0",), ("3",)), .2, .2, .2, .1, .1, 1, Strategy(),
                   perceived_balance=1.0, acceptability="high")
    loss = final_decision(s, LineupDelta(-.1, -.1, {"1": -.1, "2": .2}), True)
    assert loss["decision"] == "loss"
    own = final_decision(s, LineupDelta(.1, .1, {"1": .1, "2": -.2}), True)
    assert own["decision"] == "own" and own["acceptability"] == "medium"
    assert "kaybediyor" in own["counterpart_reasons"][0]
    assert final_decision(s, None, True)["decision"] == "unmeasured"
    assert ranked_method([None], True, "own") == "fast_fallback"
    assert ranked_method([None, LineupDelta(.1, .1)], True, "own") == "lineup_partial"


def test_replay_never_borrows_current_settings_or_undated_predictors(tmp_path):
    data = tmp_path / "real"
    snap = data / "snapshots" / "2026-11-01"
    snap.mkdir(parents=True)
    (snap / "rosters.json").write_text('{"roster_date":"2026-11-01"}')
    (snap / "league_info.json").write_text('{"version":"old"}')
    (data / "league_info.json").write_text('{"version":"future"}')
    for name in ("variance.csv", "standings_live.csv", "transactions.csv", "id_overrides.csv"):
        (data / name).write_text("future")
    work = snapshot_dir(data, dt.date(2026, 11, 1), tmp_path / "work")
    assert json.loads((work / "league_info.json").read_text())["version"] == "old"
    assert sorted(p.name for p in work.iterdir()) == ["league_info.json", "rosters.json"]
    with pytest.raises(ValueError, match="boş"):
        snapshot_dir(data, dt.date(2026, 11, 1), work)


def test_replay_requires_training_before_decision_and_unchanged_model(tmp_path):
    bundle = freeze_model(REPO_ROOT / "config", tmp_path, dt.date(2026, 11, 1))
    assert replay_model(bundle, dt.date(2026, 11, 2))["trained_through"] == "2026-11-01"
    with pytest.raises(ValueError, match="trained_through"):
        replay_model(bundle, dt.date(2026, 11, 1))
    with (bundle / "returns.yaml").open("a") as f:
        f.write("\nquestionable_play: 0.99\n")
    with pytest.raises(ValueError, match="model_version"):
        replay_model(bundle, dt.date(2026, 11, 2))


def test_replay_attendance_parameters_do_not_fall_back_to_todays_config(trade_data, tmp_path, monkeypatch):
    frozen = tmp_path / "returns.yaml"
    frozen.write_text("questionable_play: 0.25\nramp: []\n", encoding="utf-8")
    monkeypatch.setattr("fdo.api.state.load_trade_data", lambda directory, config=None: trade_data)
    monkeypatch.setattr("fdo.inseason.weekly.questionable_play", lambda: .99)
    state = AppState(tmp_path, returns_config=frozen)
    assert state.week_model("L").questionable == .25
