"""Dayanıklılık: kalan sezon maçı sezon öncesi oynama oranıyla sınırlanır, bu sezon yalnız yukarı çeker."""
from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from fdo.inseason.durability import PRIOR_GAMES, apply_durability
from fdo.inseason.injuries import apply_injuries, team_games_from
from fdo.trade import TradeEngine
from fdo.trade.data import ROS
from unit.test_inseason import data  # noqa: F401
from unit.test_injuries import _injuries


def _left(data, team, start=None):  # noqa: F811
    start = start or data.as_of
    return sum(d >= start for d in team_games_from(data.schedule)[team])


def test_caps_ros_games_and_keeps_per_game(data):  # noqa: F811
    data.stats["preseason"].loc["0", "gp"] = 41.0                          # oran .5
    data.stats["season_total"].loc["0", "gp"] = np.nan                     # kaçırılan maç düşürmez
    data.stats[ROS].loc["0", "gp"] = 2 * _left(data, "AAA")                 # kalan maçın üstünde
    before = data.stats[ROS].copy()
    out = apply_durability(data)
    ros = out.stats[ROS]
    assert out.durability.loc["0", "rate"] == pytest.approx(.5)
    assert ros.loc["0", "gp"] == pytest.approx(.5 * _left(data, "AAA"))
    np.testing.assert_allclose(ros.loc["0", "pts"] / ros.loc["0", "gp"], before.loc["0", "pts"] / before.loc["0", "gp"])
    np.testing.assert_allclose(data.stats[ROS].loc["0"], before.loc["0"])            # orijinal bozulmaz
    assert out.fingerprint != data.fingerprint and "Dayanıklılık" in out.issues[-1]


def test_playing_every_game_raises_rate_only(data):  # noqa: F811
    data.stats["preseason"].loc[["0", "4"], "gp"] = 41.0
    played = sum(d < data.as_of for d in team_games_from(data.schedule)["AAA"])
    data.stats["season_total"].loc["0", "gp"] = played                     # her maça çıktı
    data.stats["season_total"].loc["4", "gp"] = 0.0                        # hiç oynamadı
    tab = apply_durability(data).durability
    assert tab.loc["0", "rate"] == pytest.approx((PRIOR_GAMES * .5 + played) / (PRIOR_GAMES + played))
    assert tab.loc["4", "rate"] == pytest.approx(.5)


def test_rate_applies_to_games_after_known_return(data):  # noqa: F811
    ret = dt.date(2026, 11, 5)
    data.stats["preseason"].loc["1", "gp"] = 41.0
    out = apply_durability(apply_injuries(data, _injuries([{"player_id": "1", "kind": "out_until",
                                                                 "return_date": ret}])))
    left = _left(data, "BBB", ret)
    assert out.durability.loc["1", "games_left"] == left
    assert out.stats[ROS].loc["1", "gp"] <= out.durability.loc["1", "rate"] * left + 1e-9


def test_without_preseason_untouched_and_market_falls(data):  # noqa: F811
    data.stats["preseason"].loc["3", "gp"] = np.nan
    data.stats["preseason"].loc["5", "gp"] = 8.2                           # oran .1
    out = apply_durability(data)
    assert "3" not in out.durability.index
    np.testing.assert_allclose(out.stats[ROS].loc["3"], data.stats[ROS].loc["3"])
    before, after = TradeEngine(data, "L", utilization=1), TradeEngine(out, "L", utilization=1)
    assert after.vecs[after.index["5"]][0] < before.vecs[before.index["5"]][0]
