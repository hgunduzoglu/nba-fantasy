"""Algılanan değer, yanlış fiyatlama ve sat-yüksek / al-düşük öneri türleri."""
import dataclasses

import numpy as np
import pandas as pd
import pytest

from fdo.trade import TradeEngine, TradeRequest
from fdo.trade.perception import mispricing, perceived_prices, perceived_ranks
from fdo.trade.suggest import CompleteOptions, SearchOptions, complete_trade, suggest_trades
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


def _engine(trade_data, **market):  # noqa: F811
    return TradeEngine(dataclasses.replace(trade_data, **market), "L", utilization=1, horizon_weeks=4)


def test_preseason_perception_follows_the_draft_market(trade_data):  # noqa: F811
    """İsim değeri (README §13.30): ligin draftı ve Yahoo ADP'si; draft edilmeyen arkada; veri yoksa projeksiyon."""
    base = _engine(trade_data)
    ids = [p for p in base.ids if base.modeled[base.index[p]]]
    weak, strong = min(ids, key=lambda p: base.market[p]), max(ids, key=lambda p: base.market[p])
    draft = pd.DataFrame({"league_id": "L", "player_id": [weak, strong], "pick": [1.0, 2.0], "cost": [60.0, 5.0]})
    eng = _engine(trade_data, adp=pd.Series({weak: 3.0, strong: 40.0}), draft=draft)
    r = perceived_ranks(eng, "preseason")
    assert r[weak] == 1 and r[strong] == 2 and (r.drop([weak, strong]) > 2).all()
    # açık artırmada fiyat seçim sırasından önce gelir; iki kaynak çelişirse sıralar ortalanır
    flipped = _engine(trade_data, adp=pd.Series({weak: 40.0, strong: 3.0}), draft=draft)
    assert perceived_ranks(flipped, "preseason")[[weak, strong]].tolist() in ([1, 2], [2, 1])
    # başka ligin draftı etkilemez; veri yoksa eski davranış (sezon öncesi projeksiyonun z sırası)
    other = _engine(trade_data, draft=draft.assign(league_id="X"))
    pd.testing.assert_series_equal(perceived_ranks(other, "preseason"), perceived_ranks(base, "preseason"))


def test_complete_keeps_trades_the_market_sees_as_balanced(trade_data):  # noqa: F811
    """Model bir tarafı çok üstün bulsa da piyasanın dengeli gördüğü takas (isim değeriyle sat-yüksek) elenmez."""
    base = _engine(trade_data)
    rosters = base.league.rosters
    pairs = [(ta, tb, a, b) for ta in rosters for tb in rosters if ta != tb
             for a in rosters[ta] for b in rosters[tb] if base.market[a] < base.market[b]]
    fair = lambda q: base.fairness(TradeRequest(q[0], q[1], (q[2],), (q[3],)))
    ta, tb, weak, strong = min(pairs, key=fair)
    model = fair((ta, tb, weak, strong))
    assert model < .5
    eng = _engine(trade_data, adp=pd.Series({weak: 1.0, strong: 2.0}))
    opts = CompleteOptions(min_fairness=0.0, min_view=0.0, perceived="preseason")
    c = complete_trade(eng, ta, tb, (weak,), (strong,), options=opts).current
    assert c.perceived_balance > 1                                     # piyasa zayıf oyuncuyu üstün görüyor
    assert c.fairness == pytest.approx(max(model, 1 / c.perceived_balance)) and c.fairness > model
    strict = CompleteOptions(min_fairness=(model + c.fairness) / 2, min_view=0.0, perceived="preseason")
    assert any(s.request.give_b == (strong,)
               for s in complete_trade(eng, ta, tb, (weak,), (), options=strict).suggestions)
