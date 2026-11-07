"""Rol değişimi: önemli oyuncu yokken takım arkadaşının farkı, küçültme, geçerlilik ve haftalık modele etkisi."""
from __future__ import annotations

import dataclasses
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from fdo.inseason.roles import DEFAULT_DAYS, SHRINK_GAMES, match_ids, resolver, role_boosts
from fdo.inseason.weekly import WeekModel
from fdo.trade import TradeEngine
from unit.test_inseason import WEEK3, data  # noqa: F401  paylaşılan sentetik lig


def _logs(star_out_last: int = 2, games: int = 6):
    """AAA: yıldız P4 (34 dk) son ``star_out_last`` maçı kaçırdı; P8 onunla 20, onsuz 32 dakika."""
    rows = []
    for g in range(games):
        day = dt.date(2026, 10, 21) + dt.timedelta(days=2 * g)
        star = g < games - star_out_last
        for name, mins, pts in (("P4", 34 if star else 0, 25), ("P8", 20 if star else 32, 8 if star else 15),
                                ("P12", 15, 6)):
            if mins:
                rows.append({"name": name, "nba_team": "AAA", "game_date": day, "minutes": mins, "fgm": pts / 2.5,
                             "fga": pts / 1.2, "ftm": 1, "fta": 1.5, "fg3m": 1, "pts": pts, "reb": 4, "ast": 2,
                             "stl": 1, "blk": .5, "tov": 1})
    return pd.DataFrame(rows)


def test_resolver_handles_team_and_initials(data):  # noqa: F811
    one = resolver(data.players)
    assert one("P4", "AAA") == "4" and one("P4") == "4" and one("Nobody") is None
    players = pd.concat([data.players, pd.DataFrame({"name": ["N. Alexander-Walker"], "nba_team": ["ATL"],
                                                     "yahoo_positions": ["SG"], "injury_status": [""]}, index=["99"])])
    assert resolver(players)("Nickeil Alexander-Walker", "ATL") == "99"
    assert match_ids(_logs(), data.players).tolist()[:3] == ["4", "8", "12"]


def test_teammate_gains_while_the_star_is_out(data):  # noqa: F811
    data.players.loc["4", "injury_status"] = "O"
    rb = role_boosts(data, _logs())
    assert set(rb) >= {"8"} and "4" not in rb
    r = rb["8"]
    k = 2 / (2 + SHRINK_GAMES)
    assert r.absent == ("4",) and (r.n_without, r.n_with) == (2, 4)
    assert r.raw["minutes"] == pytest.approx(12) and r.delta["minutes"] == pytest.approx(12 * k)
    assert r.until == data.as_of + dt.timedelta(days=DEFAULT_DAYS)                 # dönüş bilinmiyor
    ros = data.stats["remaining_games_projection"]
    assert r.per_game["pts"] == pytest.approx(ros.loc["8", "pts"] / ros.loc["8", "gp"] + 7 * k)
    assert rb["12"].delta["minutes"] == pytest.approx(0)


def test_no_boost_when_the_star_plays_or_never_played(data):  # noqa: F811
    assert role_boosts(data, _logs()) == {}                                        # P4 sağlıklı
    data.players.loc["4", "injury_status"] = "O"
    assert role_boosts(data, _logs(star_out_last=6)) == {}                         # bütün sezon yok: önemli değil
    assert role_boosts(data, None) == {}


def test_known_return_date_limits_the_boost_and_week_model_uses_it(data):  # noqa: F811
    data.players.loc["4", "injury_status"] = "O"
    ret = WEEK3[3]
    inj = pd.DataFrame({"kind": ["out_until"], "return_date": [pd.Timestamp(ret)]}, index=["4"])
    data = dataclasses.replace(data, injuries=inj)
    rb = role_boosts(data, _logs())
    assert rb["8"].until == ret
    eng = TradeEngine(data, "L", utilization=1)
    plain, boosted = WeekModel(eng), WeekModel(eng, roles=rb)
    i = eng.index["8"]
    early, late = [d for d in WEEK3 if d < ret], [d for d in WEEK3 if d >= ret]
    assert boosted.game_unit(np.array([i]), early)[0][1] > plain.unit[i][1]       # PTS ortalaması
    np.testing.assert_allclose(boosted.game_unit(np.array([i]), late)[0], plain.unit[i])
    roster = list(eng.league.rosters["1"]) + ["8"]
    from fdo.inseason.weekly import Stint
    stints = [Stint(p, slot=k) for k, p in enumerate(roster)]
    assert boosted.team_week("1", stints, WEEK3).vector[1] >= plain.team_week("1", stints, WEEK3).vector[1]
