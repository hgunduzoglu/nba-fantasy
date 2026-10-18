import numpy as np
import pandas as pd
import pytest

from fdo.auction.advice import evaluate, prepare_auction
from fdo.auction.state import AuctionLog
from fdo.auction.values import inflation, market_prices, model_dollars


@pytest.fixture(scope="module")
def acfg(config):
    from fdo.calibration.bots import league_config

    return league_config(config, 14).with_overrides({"league": {"my_seat": 9, "draft_type": "auction"}})


def test_model_dollars_spend_league_money():
    v = pd.Series(np.linspace(10, -5, 60), index=[f"p{i}" for i in range(60)])
    d = model_dollars(v, teams=4, budget=100, rounds=10, min_bid=1)
    top = d.sort_values(ascending=False).head(40)
    assert top.sum() == pytest.approx(400) and d.min() == 1 and d.is_monotonic_decreasing


def test_market_prices_scale_and_inflation():
    aav = pd.Series([50.0, 30.0, 10.0, 1.0, np.nan], index=list("abcde"))
    m = market_prices(aav, teams=2, budget=50, rounds=2, min_bid=1)
    assert m[["a", "b", "c", "d"]].sum() == pytest.approx(100) and np.isnan(m["e"])
    assert inflation(120, 4, np.array([40, 30, 20, 10]), 1) == pytest.approx(116 / 96)


def test_auction_log_rules(acfg):
    log = AuctionLog.new(acfg)
    log.add("x", 3, 150)
    assert log.max_bid(3) == 50 - (acfg.league.rounds - 2) and log.budget_left(3) == 50
    with pytest.raises(ValueError):
        log.add("y", 3, log.max_bid(3) + 1)
    with pytest.raises(ValueError):
        log.add("x", 4, 5)
    assert log.nominator() == 2
    back, _ = AuctionLog.from_json(log.to_json())
    assert back.purchases == log.purchases
    log.undo()
    assert not log.purchases and log.nominator() == 1


def test_evaluate_board(synthetic_ds, acfg):
    a = prepare_auction(synthetic_ds, acfg)
    log = AuctionLog.new(acfg)
    b = evaluate(a, log, 9)
    t = b.table
    n = acfg.league.teams * acfg.league.rounds
    assert t["in_pool"].sum() == n and b.inflation == pytest.approx(1.0)
    assert t.loc[t["in_pool"], "price"].sum() == pytest.approx(acfg.league.teams * acfg.auction.budget)
    assert t.loc[t["in_pool"], "my_value"].sum() == pytest.approx(t.loc[t["in_pool"], "price"].sum())
    assert (t["ceiling"] <= b.my_max_bid).all()
    for k, (pid, seat, price) in enumerate(zip(t["player_id"][:3], [1, 9, 2], [70, 40, 30])):
        log.add(pid, seat, price)
    b2 = evaluate(a, log, 9)
    assert not set(b2.table["player_id"]) & log.taken and b2.my_open == acfg.league.rounds - 1
    assert b2.my_max_bid == acfg.auction.budget - 40 - (acfg.league.rounds - 2)
    w = {c: (0.0 if c == "FT_PCT" else 1.0) for c in acfg.categories}
    b3 = evaluate(a, log, 9, weights=w)
    np.testing.assert_allclose(b3.table["delta"], b3.table["delta_ecw"] - b3.table["d_FT_PCT"], atol=1e-9)
    assert len(b2.nominate(5)) <= 5 and (b2.targets(5)["gap"] > 0).all()
