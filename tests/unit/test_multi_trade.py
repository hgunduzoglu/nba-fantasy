"""Çok takımlı takas: doğrulama, iki takımlı motorla tutarlılık, kadro dengesi ve döngü önerileri."""
from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from fdo.trade import Strategy, TradeEngine, TradeError, TradeRequest
from fdo.trade.multi import (MultiSearchOptions, MultiTradeRequest, _Local, _shortlist, analyze_multi,
                             suggest_multi)
from test_trade import trade_data  # noqa: F401  (aynı sentetik lig: 4 takım × 3 oyuncu, kapasite 3)


@pytest.fixture
def eng(trade_data):  # noqa: F811
    return TradeEngine(trade_data, "L", utilization=1, horizon_weeks=4)


@pytest.mark.parametrize("moves,drops", [
    ((("0", "1", "2"),), ()),                                         # 2. takım bir şey vermiyor
    ((("3", "1", "2"), ("6", "3", "1")), ()),                         # 3, 1. takımda değil
    ((("0", "1", "1"), ("3", "2", "1")), ()),                         # veren = alan
    ((("0", "1", "2"), ("0", "2", "1")), ()),                         # aynı oyuncu iki kez
    ((("0", "1", "2"), ("3", "2", "1")), (("1", "0"),)),              # takastaki oyuncu bırakılamaz
    ((("0", "1", "2"), ("3", "2", "1")), (("3", "6"),)),              # takasta olmayan takım bırakamaz
])
def test_invalid_multi_requests_are_rejected(eng, moves, drops):
    with pytest.raises(TradeError):
        analyze_multi(eng, MultiTradeRequest(moves, drops))


def test_two_team_multi_matches_pairwise_engine(eng):
    pair = eng.analyze(TradeRequest("1", "2", ("0",), ("3",)), strategy_b=Strategy.preset("Punt FT_PCT"))
    multi = analyze_multi(eng, MultiTradeRequest((("0", "1", "2"), ("3", "2", "1"))),
                          {"2": Strategy.preset("Punt FT_PCT")})
    for t in ("1", "2"):
        for col in ("strategy_delta", "win_delta", "ecw_delta"):
            assert multi.metrics.loc[t, col] == pytest.approx(pair.metrics.loc[t, col])
    assert multi.fairness == pytest.approx(eng.fairness(TradeRequest("1", "2", ("0",), ("3",))))


def test_three_team_cycle_changes_every_roster_once(eng):
    req = MultiTradeRequest((("0", "1", "2"), ("3", "2", "3"), ("6", "3", "1")))
    r = analyze_multi(eng, req)
    assert set(r.teams) == {"1", "2", "3"}
    assert "6" in r.rosters_after["1"] and "0" not in r.rosters_after["1"]
    assert "0" in r.rosters_after["2"] and "3" in r.rosters_after["3"]
    assert r.rosters_after["4"] == eng.league.rosters["4"]
    owned = [p for t in r.rosters_after for p in r.rosters_after[t]]
    assert len(owned) == len(set(owned))
    # kategori değişimi = rakiplere karşı ortalama P farkı; ECW değişimiyle uzlaşır
    for t in r.teams:
        assert r.categories.loc[t].sum() == pytest.approx(r.metrics.loc[t, "ecw_delta"])
        assert r.metrics.loc[t, "value_in"] == pytest.approx(float(eng.market.loc[[p for p, _ in req.received(t)]].sum()))


def test_uneven_cycle_is_balanced_by_drops_and_fills(eng):
    req = MultiTradeRequest((("0", "1", "2"), ("1", "1", "2"), ("3", "2", "3"), ("6", "3", "1")))
    with pytest.raises(TradeError, match="kapasitesi"):
        analyze_multi(eng, MultiTradeRequest(req.moves, auto_balance=False))
    r = analyze_multi(eng, req)
    assert all(len(r.rosters_after[t]) == 3 for t in r.teams)
    assert len(r.adjustments["1"]["add"]) == 1 and len(r.adjustments["2"]["drop"]) == 1
    owned_before = {p for rr in eng.league.rosters.values() for p in rr}
    assert r.adjustments["1"]["add"][0] not in owned_before


def test_local_table_matches_exact_single_team_score(eng):
    strategies = {t: Strategy() for t in eng.team_ids}
    short = {t: _shortlist(eng, t, strategies[t], 3) for t in eng.team_ids}
    tab = _Local(eng, strategies, short, .65).table("1", "2", 1, 1)
    for a, (out,) in enumerate(tab.outs):
        for b, (inc,) in enumerate(tab.ins):
            rosters = dict(eng.league.rosters)
            rosters["1"] = tuple(p for p in rosters["1"] if p != out) + (inc,)
            _, m = eng.score_many(rosters, {"1": Strategy()})
            assert tab.strategy[a, b] == pytest.approx(m["1"]["strategy_delta"])
            assert tab.win[a, b] == pytest.approx(m["1"]["win_delta"])


def test_suggested_cycles_help_every_team_under_the_full_model(eng):
    # Tamamlayıcı ihtiyaçlar (her takım tek kategoriye önem verir): döngüde herkesin kazandığı takaslar vardır.
    only = {t: Strategy(f"yalnız {j}", tuple(1.0 if i == j else 0.0 for i in range(9)))
            for t, j in zip(("1", "2", "3", "4"), (3, 4, 5, 7))}
    opts = MultiSearchOptions(shortlist=3, shortlist4=3, min_fairness=0, min_strategy_gain=0, min_win_gain=-1)
    res = suggest_multi(eng, "1", strategy=only["1"], opponent_strategies=only, options=opts)
    assert res.scanned > 0 and res.evaluated >= len(res.suggestions)
    assert res.suggestions, res.message
    for s in res.suggestions:
        assert "1" in s.request.teams and len(s.request.teams) in (3, 4)
        exact = analyze_multi(eng, s.request, s.strategies)
        for t in s.request.teams:
            assert exact.metrics.loc[t, "strategy_delta"] == pytest.approx(s.metrics[t]["strategy_delta"])
            assert exact.metrics.loc[t, "strategy_delta"] > 0
    scores = [s.score for s in res.suggestions]
    assert scores == sorted(scores, reverse=True)
    assert np.isfinite(scores).all()


def test_multi_suggestions_stop_after_deadline(eng):
    res = suggest_multi(eng, "1", analysis_date=dt.date(2027, 3, 5))
    assert not res.suggestions and "son tarihi" in res.message
