"""Finalist önerilerinin günlük kadroyla yeniden sıralanması (``fdo.inseason.lineup_rank``)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fdo.inseason.lineup_rank import LineupDelta, lineup_deltas, multi_lineup_deltas, rerank
from fdo.inseason.season import SeasonSim
from fdo.inseason.weekly import WeekModel
from fdo.inseason.weeks import league_weeks
from fdo.trade import TradeEngine, TradeRequest
from fdo.trade.multi import MultiSuggestion, MultiTradeRequest, resolve_multi
from fdo.trade.strategy import Strategy
from fdo.trade.suggest import Suggestion
from unit.test_inseason import data  # noqa: F401  paylaşılan sentetik lig
from unit.test_season import _fixtures


@pytest.fixture
def setup(data):  # noqa: F811
    lg = data.leagues["L"]
    lg.settings["Playoffs"] = "2 teams - Week 22 (ends Sunday, Apr 4)"
    eng = TradeEngine(data, "L", utilization=1)
    st = pd.DataFrame({"wins": [7, 2, 5, 4], "losses": [2, 7, 4, 5], "ties": 0}, index=["1", "2", "3", "4"])
    weeks = league_weeks(data.schedule, lg.settings, lg.config)
    return eng, SeasonSim(WeekModel(eng), weeks, _fixtures(range(1, 20)), st, data.as_of, waiver_order=("3", "4"))


def _sug(req: TradeRequest, score: float, other: Strategy = Strategy()) -> Suggestion:
    return Suggestion(req, score, score, 0.0, 0.0, 0.0, 1.0, other)


def test_lineup_profile_sums_to_the_simulated_lineup_ecw(setup):
    eng, sim = setup
    pair = {"1": Strategy(), "2": Strategy()}
    rosters, _, il = eng.resolve(TradeRequest("1", "2", ("0",), ("4",)), pair)
    prof = sim.lineup_profile(rosters, injuries=il, first=("1", "2"), strategies=pair)
    run = sim.run(rosters, n_sims=50, seed=1, injuries=il, first=("1", "2"), strategies=pair)
    assert prof.shape == (4, 9) and ((prof >= 0) & (prof <= 1)).all()
    np.testing.assert_allclose(prof.sum(axis=1), run.ecw)


def test_lineup_deltas_measure_the_trade_against_the_same_base_and_weight_by_strategy(setup):
    eng, sim = setup
    reb = Strategy("yalnız REB", tuple(1.0 if i == 4 else 0.0 for i in range(9)))
    good, bad = TradeRequest("1", "2", ("0",), ("4",)), TradeRequest("1", "2", ("0",), ("999",))
    out = lineup_deltas(sim, eng, "1", reb, [_sug(good, .1), _sug(bad, .2)])
    assert out[1] is None                                                     # çözülemeyen öneri ölçülmez
    pair = {"1": reb, "2": Strategy()}
    rosters, _, il = eng.resolve(good, pair)
    d = (sim.lineup_profile(rosters, injuries=il, first=("1", "2"), strategies=pair)
         - sim.lineup_profile(first=("1", "2"), strategies=pair))[sim.tix["1"]]
    assert out[0].ecw == pytest.approx(d.sum())
    assert out[0].strategy == pytest.approx(d[4] * 9)                         # yalnız REB ağırlığı (normalize × 9)


def test_rerank_orders_by_lineup_gain_and_keeps_unmeasured_last():
    reqs = [TradeRequest("1", "2", (str(i),), (str(10 + i),)) for i in range(4)]
    sugs = [_sug(r, s) for r, s in zip(reqs, (.4, .3, .2, .1))]
    deltas = [LineupDelta(-.1, -.1), None, LineupDelta(.2, .1), LineupDelta(.05, .3)]
    ranked, ds = rerank(sugs, deltas)
    assert [s.score for s in ranked] == [.2, .1, .4, .3] and ds[-1] is None
    top, _ = rerank(sugs, deltas, 2)
    assert [s.score for s in top] == [.2, .1]


def test_multi_lineup_deltas_use_all_teams_strategies_and_the_same_measure(setup):
    eng, sim = setup
    st = {"1": Strategy(), "2": Strategy(), "3": Strategy()}
    req = MultiTradeRequest((("0", "1", "2"), ("4", "2", "3"), ("8", "3", "1")))
    (d,) = multi_lineup_deltas(sim, eng, "1", [MultiSuggestion(req, (1, 1, 1), .1, {}, 1.0, st)])
    rosters, _, il = resolve_multi(eng, req, st)
    first = tuple(req.teams)
    diff = (sim.lineup_profile(rosters, injuries=il, first=first, strategies=st)
            - sim.lineup_profile(first=first, strategies=st))[sim.tix["1"]]
    assert d.ecw == pytest.approx(diff.sum()) and d.strategy == pytest.approx(diff.sum())   # dengeli: ikisi aynı
