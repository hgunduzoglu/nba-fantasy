"""Dated roster transitions: an IL activation and its capacity cost are inseparable."""
import datetime as dt
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from fdo.inseason.season import SeasonSim
from fdo.inseason.weekly import WeekModel
from fdo.inseason.weeks import LeagueWeeks
from fdo.trade import TradeEngine
from fdo.trade.strategy import Strategy
from unit.test_trade import trade_data  # noqa: F401
from unit.test_season import _fixtures

MONDAY = dt.date(2026, 11, 2)
TUESDAY = MONDAY + dt.timedelta(days=1)
PTS = Strategy("PTS", (0, 0, 0, 1, 0, 0, 0, 0, 0))


@pytest.fixture
def dated_sim(trade_data):
    lg = trade_data.leagues["L"]
    slots = {s: 0 for s in lg.config.roster.slots}
    slots["UTIL"] = 1
    cfg = lg.config.with_overrides({"league": {"rounds": 1}, "roster": {"slots": slots, "active_slots": ["UTIL"]},
                                   "unverified": {"il_slots": 1}})
    rosters = {"1": ("0", "1"), "2": ("3",), "3": ("4",), "4": ("5",)}
    il = {t: frozenset({"1"}) if t == "1" else frozenset() for t in rosters}
    lg = replace(lg, config=cfg, rosters=rosters, injury_rosters=il, roster_date=MONDAY)
    schedule = pd.DataFrame({"game_date": [MONDAY, TUESDAY, MONDAY + dt.timedelta(days=7),
                                           TUESDAY + dt.timedelta(days=7)], "home_team": "SYN", "away_team": "OTHER"})
    injuries = pd.DataFrame({"kind": ["out_until"], "return_date": [TUESDAY]}, index=["1"])
    for frame in trade_data.stats.values():
        frame["pts"] = 100.
        frame.loc["1", "pts"] = 300.
    trade_data.players.loc["1", "injury_status"] = "INJ"
    data = replace(trade_data, leagues={"L": lg}, schedule=schedule, injuries=injuries, as_of=MONDAY)
    eng = TradeEngine(data, "L", utilization=1, free_moves=False)
    utility = np.ones(len(eng.ids))
    utility[eng.index["1"]] = 3.
    eng._utility_cache[PTS] = utility
    model = WeekModel(eng, questionable=1)
    model.unit = np.zeros_like(model.unit)
    model.unit[:, 1] = 10.
    model.unit[1, 1] = 30.
    model.availability[:] = 1.
    weeks = LeagueWeeks(pd.DataFrame({"start": [MONDAY, MONDAY + dt.timedelta(days=7)],
        "end": [MONDAY + dt.timedelta(days=6), MONDAY + dt.timedelta(days=13)], "n_days": [7, 7],
        "playoff": [False, True]}, index=[1, 2]), playoff_weeks=(2,))
    return SeasonSim(model, weeks, _fixtures((1, 2)), None, MONDAY)


def test_current_week_activation_counts_backup_before_and_returner_after(dated_sim):
    sim = dated_sim
    result = sim.vector("1", ("0", "1"), 1, frozenset({"1"}), PTS)
    assert result[1] == 40                                      # Monday 10 + Tuesday 30, not just 10


def test_activation_and_drop_share_the_same_date_and_preserve_capacity(dated_sim, monkeypatch):
    sim = dated_sim
    recorded = []
    original = sim.model.team_week
    def record(team, stints, days, *args, **kwargs):
        if team == "1":
            recorded.append((stints, days))
        return original(team, stints, days, *args, **kwargs)
    monkeypatch.setattr(sim.model, "team_week", record)
    sim.vector("1", ("0", "1"), 1, frozenset({"1"}), PTS)
    stints, days = recorded[-1]
    active = lambda day: {s.player_id for s in stints if s.first <= days.index(day) <= s.last}
    assert active(MONDAY) == {"0"} and active(TUESDAY) == {"1"}
    assert all(len(active(day)) <= 1 for day in days)
    assert sim.drop_schedule(("0", "1"), frozenset({"1"}), PTS) == {"0": TUESDAY}


def test_player_kept_on_il_does_not_trigger_a_capacity_drop(dated_sim):
    sim = dated_sim
    # The existing strategy policy declines activation when the returner is worse.
    utility = sim.engine._utility_array(PTS)
    sim.engine._utility_cache[PTS] = utility.copy()
    sim.engine._utility_cache[PTS][sim.engine.index["1"]] = utility[sim.engine.index["0"]] - 1
    assert sim.drop_schedule(("0", "1"), frozenset({"1"}), PTS) == {}
    assert sim.vector("1", ("0", "1"), 1, frozenset({"1"}), PTS)[1] == 20


def test_known_return_does_not_count_in_days_before_activation(dated_sim):
    sim = dated_sim
    sim.model.return_date["1"] = TUESDAY + dt.timedelta(days=7)
    assert sim.vector("1", ("0", "1"), 1, frozenset({"1"}), PTS)[1] == 20


def test_activation_into_a_free_spot_needs_no_drop(dated_sim):
    sim = dated_sim
    plan = sim.roster_plan(("1",), frozenset({"1"}), PTS)
    assert plan.effective(MONDAY).active == ()
    assert plan.effective(TUESDAY).active == ("1",)
    assert plan.changes[0].drop is None
    assert sim.vector("1", ("1",), 1, frozenset({"1"}), PTS)[1] == 30


def test_unknown_return_in_a_long_current_week_starts_on_assumed_date(dated_sim):
    sim = dated_sim
    sim.model.return_date.pop("1")
    sim.model.injury_known.remove("1")
    sim.weeks.weeks.loc[1, "end"] = MONDAY + dt.timedelta(days=13)
    plan = sim.roster_plan(("0", "1"), frozenset({"1"}), PTS)
    assert plan.effective(TUESDAY).active == ("0",)
    assert plan.effective(MONDAY + dt.timedelta(days=7)).active == ("1",)
    # The stale snapshot INJ status cannot suppress an explicitly planned activation.
    assert sim.vector("1", ("0", "1"), 1, frozenset({"1"}), PTS)[1] == 80
