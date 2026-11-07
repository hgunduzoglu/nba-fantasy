"""Sit/start: eşleşmeye göre günlük düzen, oran koruması ve Yahoo düzeniyle karşılaştırma."""
from __future__ import annotations

import numpy as np

from fdo.inseason.sitstart import SIT_BELOW, plan_week, today_changes
from fdo.inseason.weekly import WeekModel
from fdo.trade import TradeEngine
from unit.test_inseason import WEEK3, data  # noqa: F401  paylaşılan sentetik lig

COUNTS = ("fg3m", "pts", "reb", "ast", "stl", "blk")


def _model(data):  # noqa: F811
    return WeekModel(TradeEngine(data, "L", utilization=1))


def test_plan_fills_slots_by_matchup_value_and_never_loses(data):  # noqa: F811
    model = _model(data)
    plan = plan_week(model, "1", "2", WEEK3)
    tw = plan.week
    assert ((tw.slots >= 0).sum(axis=1) <= 2).all()                         # 2 aktif slot (PG, C)
    assert plan.after.strategy_score >= plan.before.strategy_score - 1e-9
    assert not (plan.sat & ~tw.playing).any()                               # yalnız maçı olan oturtulur
    assert (plan.value[plan.sat.any(axis=0)] < SIT_BELOW).all()
    started = (tw.slots >= 0).any(axis=0)
    assert (plan.value[started] >= SIT_BELOW).all()


def test_ratio_protection_sits_low_percentage_shooters_when_counts_are_settled(data):  # noqa: F811
    model = _model(data)
    # sayım kategorileri ve FT% kesinleşmiş; yalnız FG% başa baş (%45'e %44.6)
    mine = {**{s: 1e5 for s in COUNTS}, "tov": 0, "fgm": 450, "fga": 1000, "ftm": 900, "fta": 1000}
    opp = {**{s: 0 for s in COUNTS}, "tov": 1e5, "fgm": 446, "fga": 1000, "ftm": 0, "fta": 1000}
    plan = plan_week(model, "1", "2", WEEK3, acc_mine=mine, acc_opp=opp)
    f = data.stats["remaining_games_projection"]
    pct = (f["fgm"] / f["fga"]).reindex(plan.players).to_numpy()
    games = plan.week.playing.any(axis=0)
    sat = plan.sat.any(axis=0)
    assert sat.any() and (pct[sat] < .45).all()                              # takımın FG%'sini düşürenler oturur
    started = (plan.week.slots >= 0).any(axis=0)
    assert (pct[started] > .45).all()
    assert plan.after.p[0] > plan.before.p[0] and np.allclose(plan.after.p[2:], plan.before.p[2:], atol=1e-6)
    assert games[sat].all()


def test_today_changes_compare_with_yahoo_slots(data):  # noqa: F811
    model = _model(data)
    mine = {**{s: 1e5 for s in COUNTS}, "tov": 0, "fgm": 450, "fga": 1000, "ftm": 900, "fta": 1000}
    opp = {**{s: 0 for s in COUNTS}, "tov": 1e5, "fgm": 446, "fga": 1000, "ftm": 0, "fta": 1000}
    plan = plan_week(model, "1", "2", WEEK3, acc_mine=mine, acc_opp=opp)
    d = next(i for i in range(len(WEEK3)) if plan.sat[i].any() or (plan.week.slots[i] >= 0).any())
    day = WEEK3[d]
    sat = [p for j, p in enumerate(plan.players) if plan.sat[d, j]]
    start = [p for j, p in enumerate(plan.players) if plan.week.slots[d, j] >= 0]
    yahoo = {**{p: "PG" for p in sat}, **{p: "BN" for p in start}}         # tam tersi düzen
    ch = today_changes(plan, yahoo, day)
    assert {r["player_id"] for r in ch["sit"]} == set(sat) and all(r["negative"] for r in ch["sit"])
    assert {r["player_id"] for r in ch["start"]} == set(start) and all(r["slot"] for r in ch["start"])
    same = {**{p: "BN" for p in sat}, **{p: plan.slot_names[plan.week.slots[d, plan.players.index(p)]] for p in start}}
    assert today_changes(plan, same, day) == {"start": [], "sit": []}
