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


def test_zero_ros_with_known_return_is_filled(data):  # noqa: F811
    ret = dt.date(2026, 11, 5)
    data.stats["preseason"].loc["1", "gp"] = 41.0                          # oran .5
    pre_pg = data.stats["preseason"].loc["1", "pts"] / 41.0
    season_pg = data.stats["season_total"].loc["1", "pts"] / data.stats["season_total"].loc["1", "gp"]
    seen = float(data.stats["season_total"].loc["1", "gp"])
    data.stats[ROS].loc["1", [*data.stats[ROS].columns]] = 0.0              # Yahoo: 0 maç
    data.stats[ROS].loc["20", "gp"] = 0.0                                  # boştaki, dönüşü bilinmiyor → dokunulmaz
    out = apply_durability(apply_injuries(data, _injuries([
        {"player_id": "1", "kind": "out_until", "return_date": ret},
        {"player_id": "20", "kind": "day_to_day", "return_date": None}])))
    ros = out.stats[ROS]
    left = _left(data, "BBB", ret)
    assert ros.loc["1", "gp"] == pytest.approx(.5 * left)
    w = seen / (seen + PRIOR_GAMES)
    assert ros.loc["1", "pts"] / ros.loc["1", "gp"] == pytest.approx(w * season_pg + (1 - w) * pre_pg)
    assert ros.loc["20", "gp"] == 0 and bool(out.durability.loc["1", "ros_filled"])
    assert data.stats[ROS].loc["1", "gp"] == 0                             # orijinal bozulmaz
    eng = TradeEngine(out, "L", utilization=1)
    assert eng.modeled[eng.index["1"]] and not eng.modeled[eng.index["20"]]
    assert any("dolduruldu" in m for m in out.issues)


def test_rostered_player_without_ros_row_is_filled_from_today(data):  # noqa: F811
    data.stats["preseason"].loc[["0", "4", "20"], "gp"] = 41.0
    data.stats[ROS].loc[["0", "4", "20"], [*data.stats[ROS].columns]] = np.nan   # sayfalarda satırı yok
    data.players.loc["4", "injury_status"] = "NA"                          # aktif değil → dokunulmaz
    out = apply_durability(data)
    ros = out.stats[ROS]
    assert ros.loc["0", "gp"] == pytest.approx(.5 * _left(data, "AAA"))    # kadroda, sağlıklı
    assert np.isnan(ros.loc["4", "gp"]) and np.isnan(ros.loc["20", "gp"])   # NA; kadrosuz boştaki


def test_stale_ros_per_game_is_replaced_by_season_weighted_rates(data):  # noqa: F811
    from fdo.inseason.durability import STALE_PRIOR_GAMES
    from fdo.types import STATS
    season, pre = data.stats["season_total"], data.stats["preseason"]
    season.loc["2", "gp"] = max(float(season.loc["2", "gp"]), 6.0)
    data.stats[ROS].loc["2", list(STATS)] *= .1                              # Yahoo: maç başı onda bir
    gp_before = float(data.stats[ROS].loc["2", "gp"])
    out = apply_durability(data)
    ros = out.stats[ROS]
    seen = float(season.loc["2", "gp"])
    w = seen / (seen + STALE_PRIOR_GAMES)
    want = w * season.loc["2", "pts"] / seen + (1 - w) * pre.loc["2", "pts"] / pre.loc["2", "gp"]
    assert ros.loc["2", "pts"] / ros.loc["2", "gp"] == pytest.approx(want)
    assert ros.loc["2", "gp"] <= gp_before + 1e-9                           # maç sayısı Yahoo'nun (ya da tavan)
    assert bool(out.durability.loc["2", "ros_stale"]) and not out.durability["ros_stale"].drop("2").any()
    assert any("bayat" in m for m in out.issues)


def test_yahoo_rates_shrink_toward_season_by_category_and_minutes(data):  # noqa: F811
    import pandas as pd
    from fdo.inseason.durability import SHRINK_GAMES, YAHOO, _minutes_factor
    season = data.stats["season_total"]
    season.loc["3", "gp"] = 6.0
    yahoo_pg = data.stats[ROS].loc["3", "pts"] / data.stats[ROS].loc["3", "gp"]
    yahoo_stl = data.stats[ROS].loc["3", "stl"] / data.stats[ROS].loc["3", "gp"]
    out = apply_durability(data)
    ros, n = out.stats[ROS], 6.0
    cur = lambda c: season.loc["3", c] / n                                    # noqa: E731
    w = lambda c: n / (n + SHRINK_GAMES[c])                                    # noqa: E731
    assert ros.loc["3", "pts"] / ros.loc["3", "gp"] == pytest.approx((1 - w("pts")) * yahoo_pg + w("pts") * cur("pts"))
    assert ros.loc["3", "stl"] / ros.loc["3", "gp"] == pytest.approx((1 - w("stl")) * yahoo_stl + w("stl") * cur("stl"))
    assert w("stl") < w("pts")                                                 # top çalmada Yahoo'ya daha çok güvenilir
    y = out.stats[YAHOO]                                                       # kaydırma öncesi Yahoo satırı korunur
    assert y.loc["3", "pts"] / y.loc["3", "gp"] == pytest.approx(yahoo_pg)
    assert bool(out.durability.loc["3", "ros_shrunk"])
    # dakika: son 5 maçta dakikası artan oyuncunun maç başı değeri çeyrek ağırlıkla artar
    name, team = str(data.players.loc["3", "name"]), str(data.players.loc["3", "nba_team"])
    days = [data.as_of - dt.timedelta(days=i) for i in range(10, 0, -1)]
    logs = pd.DataFrame({"name": name, "nba_team": team, "game_date": days, "minutes": [20.0] * 5 + [30.0] * 5})
    f = _minutes_factor(data, logs, set())
    assert f[str("3")] == pytest.approx((.75 * 25 + .25 * 30) / 25)
    assert _minutes_factor(data, logs.iloc[:4], set()) == {}                   # az maç: dokunulmaz
