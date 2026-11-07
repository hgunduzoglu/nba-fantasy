"""Add/drop: waiver uygunluğu, kritik kategoriler, tek hamleler ve waiver tarihine uyan streaming."""
from __future__ import annotations

import datetime as dt

import numpy as np

from fdo.inseason.adddrop import (OTHER_WEIGHT, available_from, critical_categories, critical_strategy, pick_critical,
                                  waiver_days)
from fdo.inseason.weekly import WeekModel
from fdo.trade import TradeEngine
from fdo.trade.strategy import CATEGORIES
from unit.test_inseason import WEEK3, data  # noqa: F401  paylaşılan sentetik lig


def test_waiver_days_and_availability():
    assert waiver_days({"Waiver Time": "2 days"}) == 2 and waiver_days({"Waiver Time": "No waivers"}) == 0
    av = available_from({"16": dt.date(2026, 11, 9), "17": None}, dt.date(2026, 11, 7), {"Waiver Time": "1 day"})
    assert av == {"16": dt.date(2026, 11, 9), "17": dt.date(2026, 11, 8)}


def test_pick_and_weight_critical_categories():
    lev = np.array([0.0, 0.05, 0.0, 0.01, 0.0, 0.0, 0.0, 0.09, 0.0])
    assert pick_critical(lev) == ["BLK", "FT_PCT"]
    assert pick_critical(np.full(9, 0.001)) == ["FG_PCT"]                    # eşik altı: yine en iyisi
    s = critical_strategy(["BLK"])
    assert s.weights[CATEGORIES.index("BLK")] == 1 and s.weights[0] == OTHER_WEIGHT and s.name == "Kritik: BLK"


def test_critical_categories_are_zero_when_settled(data):  # noqa: F811
    model = WeekModel(TradeEngine(data, "L", utilization=1))
    counts = ("fg3m", "pts", "reb", "ast", "stl", "blk")
    mine = {**{s: 1e5 for s in counts}, "tov": 0, "fgm": 450, "fga": 1000, "ftm": 900, "fta": 1000}
    opp = {**{s: 0 for s in counts}, "tov": 1e5, "fgm": 446, "fga": 1000, "ftm": 0, "fta": 1000}
    base = model.outlook("1", "2", WEEK3, acc_mine=mine, acc_opp=opp)
    lev = critical_categories(model, base)
    assert lev[0] > 0 and np.allclose(lev[1:], 0, atol=1e-6)                 # yalnız FG% açık
    assert pick_critical(lev) == ["FG_PCT"]


def test_single_moves_and_stream_respect_waiver_dates(data):  # noqa: F811
    model = WeekModel(TradeEngine(data, "L", utilization=1))
    base = model.outlook("1", "2", WEEK3)
    drops = ["0", "1"]
    free = model.single_moves(base, droppable=drops)
    assert len(free) and set(free["drop"]) <= set(drops) and (free["gain"].diff().dropna() <= 1e-12).all()
    best = free.iloc[0]["add"]
    late = {best: WEEK3[-1] + dt.timedelta(days=1)}                           # bu hafta serbest kalmıyor
    blocked = model.single_moves(base, droppable=drops, available_from=late)
    assert best not in set(blocked["add"])
    mid = {best: WEEK3[3]}
    moved = model.single_moves(base, droppable=drops, available_from=mid)
    if best in set(moved["add"]):
        assert moved.set_index("add").loc[best, "day"] >= WEEK3[3]
    plan = model.stream(base, moves=3, droppable=drops, available_from=mid)
    assert all(m.day >= WEEK3[3] for m in plan.moves if m.add == best)
