"""Algılanan değer, yanlış fiyatlama ve sat-yüksek / al-düşük öneri türleri."""
import numpy as np
import pytest

from fdo.trade import TradeEngine
from fdo.trade.perception import mispricing, perceived_prices
from fdo.trade.suggest import SearchOptions, suggest_trades
from unit.test_trade import trade_data  # noqa: F401  paylaşılan sentetik lig

COUNT = ["fgm", "fga", "ftm", "fta", "fg3m", "pts", "reb", "ast", "stl", "blk", "tov"]


def test_identical_sources_have_no_mispricing(trade_data):  # noqa: F811
    eng = TradeEngine(trade_data, "L", utilization=1, horizon_weeks=4)
    p = perceived_prices(eng, "season_total")
    m = mispricing(eng, p)
    np.testing.assert_allclose(m["edge"], 0, atol=1e-9)
    with pytest.raises(ValueError):
        perceived_prices(eng, "x")


def _scaled(trade_data, pid, k):  # noqa: F811
    f = trade_data.stats["season_total"]
    f.loc[pid, ["pts", "reb", "ast", "fg3m", "stl", "blk"]] *= k
    f.loc[pid, "tov"] /= k
    return TradeEngine(trade_data, "L", utilization=1, horizon_weeks=4)


def test_sell_high_uses_overvalued_own_player(trade_data):  # noqa: F811
    base = TradeEngine(trade_data, "L", utilization=1, horizon_weeks=4)
    hot = min(base.league.rosters["1"], key=lambda p: base.market[p])          # takım 1'in en zayıfı
    eng = _scaled(trade_data, hot, 4.0)
    m = mispricing(eng, perceived_prices(eng, "season_total"))
    assert m.iloc[0]["player_id"] == hot and m.iloc[0]["edge"] > 0
    thr = .5 * float(m.iloc[0]["edge"])
    opts = SearchOptions(max_evaluations=400, mode="sell_high", perceived="season_total",
                         min_perceived_balance=.5, min_edge=thr, min_strategy_gain=0.0)
    r = suggest_trades(eng, "1", options=opts)
    assert r.suggestions
    for s in r.suggestions:
        assert hot in s.request.give_a and s.key_players == (hot,) and s.perceived_balance >= .5
        assert s.own_strategy_delta >= 0 and s.mode == "sell_high"


def test_buy_low_targets_undervalued_opponent_player(trade_data):  # noqa: F811
    base = TradeEngine(trade_data, "L", utilization=1, horizon_weeks=4)
    cold = max(base.league.rosters["1"], key=lambda p: base.market[p])         # güçlü takım 1'in en iyisi
    eng = _scaled(trade_data, cold, .1)
    edge = (perceived_prices(eng, "season_total") - eng.market).dropna()
    assert edge[cold] == edge.min() < 0
    thr = .5 * abs(edge[cold])                       # yalnızca belirgin biçimde ucuz görünen oyuncu
    opts = SearchOptions(max_evaluations=400, mode="buy_low", perceived="season_total",
                         min_perceived_balance=.5, min_edge=thr, min_strategy_gain=0.0)
    r = suggest_trades(eng, "3", options=opts)                                  # zayıf takım 3 alıcı
    assert r.suggestions
    for s in r.suggestions:
        assert s.key_players and all(-edge[k] >= thr and k in s.request.give_b for k in s.key_players)
    assert any(cold in s.key_players for s in r.suggestions)
    mutual = suggest_trades(eng, "3", options=SearchOptions(max_evaluations=400, min_fairness=.1,
                                                            min_strategy_gain=.00001))
    assert all(s.mode == "mutual" and np.isnan(s.perceived_balance) for s in mutual.suggestions)
