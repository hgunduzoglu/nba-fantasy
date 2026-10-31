"""Sakatlık dönüş tarihleri: CBS ayrıştırma, yorum, eşleşme, ROS kısma ve haftalık gün maskesi."""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from fdo.inseason.injuries import apply_injuries, interpret, match_players, parse_cbs
from fdo.inseason.weekly import WeekModel
from fdo.trade import TradeEngine
from fdo.trade.data import ROS
from unit.test_inseason import WEEK3, data  # noqa: F401

START = dt.date(2026, 10, 20)
PAGE = """
<div class="TableBase-title"><a href="/nba/teams/BKN/brooklyn-nets/">x</a></div>
<table><tbody>
<tr class="TableBase-bodyTr"><td><span class="CellPlayerName--short"><a>N. Claxton</a></span>
<span class="CellPlayerName--long"><span><a href="/p/1/">Nicolas Claxton</a></span></span></td>
<td> C </td><td><span class="CellGameDate"> Fri, Oct 30 </span></td><td> Ankle </td>
<td> Expected to be out until at least Nov 4 </td></tr>
</tbody></table>
<div class="TableBase-title"><a href="/nba/teams/GS/golden-state/">y</a></div>
<table><tbody>
<tr class="TableBase-bodyTr"><td><span class="CellPlayerName--long"><a>A &amp; B Player</a></span></td>
<td> G </td><td> Sat </td><td> Knee </td><td> Out for the season </td></tr>
</tbody></table>
"""


def test_parse_and_interpret():
    df = parse_cbs(PAGE)
    assert list(df["name"]) == ["Nicolas Claxton", "A & B Player"] and list(df["nba_team"]) == ["BKN", "GS"]
    assert interpret(df.loc[0, "status_text"], START) == ("out_until", dt.date(2026, 11, 4))
    assert interpret("Expected to be out until at least Jan 2", START) == ("out_until", dt.date(2027, 1, 2))
    assert interpret("Out for the season", START) == ("season", None)
    assert interpret("Game Time Decision", START)[0] == "day_to_day"
    assert interpret("something else", START) == ("unknown", None)


def test_match_falls_back_to_team_last_name_initial():
    players = pd.DataFrame({"name": ["Nic Claxton", "Nick Smith"], "nba_team": ["BKN", "CHA"]}, index=["9", "8"])
    m = match_players(parse_cbs(PAGE), players, START)
    assert list(m.index) == ["9"] and m.loc["9", "return_date"] == dt.date(2026, 11, 4)


def _injuries(rows):
    return pd.DataFrame(rows).set_index("player_id")


def test_apply_cuts_ros_only_when_return_leaves_fewer_games(data):  # noqa: F811
    inj = _injuries([{"player_id": "0", "kind": "season", "return_date": None},
                     {"player_id": "1", "kind": "out_until", "return_date": dt.date(2026, 11, 7)},
                     {"player_id": "3", "kind": "day_to_day", "return_date": None}])
    before = data.stats[ROS].copy()
    out = apply_injuries(data, inj)
    ros = out.stats[ROS]
    assert ros.loc["0", "gp"] == 0 and ros.loc["0", "pts"] == 0                      # sezon boyu yok
    left = out.injuries.loc["1", "games_after_return"]
    assert ros.loc["1", "gp"] == pytest.approx(min(before.loc["1", "gp"], left))
    np.testing.assert_allclose(ros.loc["3"], before.loc["3"])                        # gün gün: değişmez
    np.testing.assert_allclose(data.stats[ROS].loc["0"], before.loc["0"])            # orijinal bozulmaz
    assert out.fingerprint != data.fingerprint and "Sakatlık" in out.issues[-1]


def test_weekly_model_waits_for_return_date(data):  # noqa: F811
    data.players.loc["0", "injury_status"] = "O"
    ret = WEEK3[3]
    out = apply_injuries(data, _injuries([{"player_id": "0", "kind": "out_until", "return_date": ret}]))
    m = WeekModel(TradeEngine(out, "L", utilization=1))
    o = m.outlook("1", "2", WEEK3, week=3)
    row = o.mine.grid.loc["0"]
    before = [d for d in WEEK3[:3] if m.has_game("0", d)]
    assert set(row.iloc[:3]) <= {"", "✕"} and (row.iloc[:3] == "✕").sum() == len(before)   # dönüşten önce oynamaz
    after = [d for d in WEEK3[3:] if m.has_game("0", d)]
    assert set(row.iloc[3:]) <= {"", "▶", "B"} and (row.iloc[3:] != "").sum() == len(after)  # O olsa da dönüşte oynar
