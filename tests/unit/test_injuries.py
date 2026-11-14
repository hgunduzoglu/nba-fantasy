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


def test_questionable_players_sit_only_in_the_scenario(data):  # noqa: F811
    from fdo.api.inseason import out_statuses
    from fdo.api.schemas import WeeklyIn
    from fdo.inseason.weekly import DEFAULT_OUT, QUESTIONABLE

    data.players.loc["0", "injury_status"] = "Q"
    known = apply_injuries(data, _injuries([{"player_id": "0", "kind": "day_to_day", "return_date": None}]))
    for d in (data, known):                                                   # CBS'te olsun olmasın
        eng = TradeEngine(d, "L", utilization=1)
        assert WeekModel(eng).playable("0")                                    # varsayılan: Q oynar
        assert not WeekModel(eng, out_statuses=DEFAULT_OUT + QUESTIONABLE).playable("0")
        assert WeekModel(eng, out_statuses=DEFAULT_OUT + QUESTIONABLE).playable("0", use_status=False)  # gelecek haftalar
    assert out_statuses(WeeklyIn(team="1")) == DEFAULT_OUT
    assert set(out_statuses(WeeklyIn(team="1", questionable_out=True, sit_out=False))) == {"NA", "INJ", "SUSP", *QUESTIONABLE}


def test_return_ramp_scales_rest_of_season_by_the_lost_minutes(data, tmp_path):  # noqa: F811
    from fdo.inseason.injuries import DEFAULT_RAMP, apply_return_ramp, return_ramp, team_games_from

    ret = dt.date(2026, 11, 7)
    out = apply_injuries(data, _injuries([{"player_id": "1", "kind": "out_until", "return_date": ret},
                                          {"player_id": "3", "kind": "day_to_day", "return_date": None}]))
    before = out.stats[ROS].copy()
    ramped = apply_return_ramp(out, (0.5, 0.75))
    team = data.players.loc["1", "nba_team"]
    left = sum(d >= ret for d in team_games_from(data.schedule)[team])
    factor = (left - 0.75) / left
    assert ramped.stats[ROS].loc["1", "gp"] == pytest.approx(before.loc["1", "gp"] * factor)
    np.testing.assert_allclose(ramped.stats[ROS].loc["1", "pts"] / ramped.stats[ROS].loc["1", "gp"],
                               before.loc["1", "pts"] / before.loc["1", "gp"])           # maç başı aynı
    np.testing.assert_allclose(ramped.stats[ROS].loc["3"], before.loc["3"])               # dönüş tarihi yok
    assert "dakika" in ramped.issues[-1] and ramped.fingerprint != out.fingerprint
    assert apply_return_ramp(out, ()) is out and apply_return_ramp(data, (0.5,)) is data  # kapalı / sakatlık yok
    assert return_ramp(tmp_path / "yok.yaml") == DEFAULT_RAMP
    (tmp_path / "r.yaml").write_text("ramp: [0.6, 1.4]\n", encoding="utf-8")
    assert return_ramp(tmp_path / "r.yaml") == (0.6, 1.0)
