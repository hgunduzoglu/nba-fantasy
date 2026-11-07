"""Geçmiş haftalar: kategori değerleri, lig sırası (TO ters), sezon toplamı ve süren hafta."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from fdo.inseason.history import category_values, rank_table, team_history
from fdo.inseason.live import LiveLeague


def _t(pts, fgm=40, fga=100, tov=10):
    return {"fgm": fgm, "fga": fga, "ftm": 8, "fta": 10, "fg3m": 5, "pts": pts, "reb": 30, "ast": 20, "stl": 5,
            "blk": 3, "tov": tov}


def test_values_and_ranks():
    assert category_values(_t(100))["FG_PCT"] == pytest.approx(.4)
    values, ranks = rank_table({"1": _t(100, tov=5), "2": _t(120, fgm=50, tov=9), "3": _t(120, tov=20)})
    assert ranks.loc["2", "PTS"] == 1 and ranks.loc["3", "PTS"] == 1 and ranks.loc["1", "PTS"] == 3   # eşitlik paylaşılır
    assert ranks.loc["1", "TOV"] == 1 and ranks.loc["3", "TOV"] == 3                                   # TO: az olan iyi
    assert ranks.loc["2", "FG_PCT"] == 1


def test_team_history_sums_finished_weeks_and_adds_live_week(tmp_path):
    ms = [{"league_id": "L", "week": w, "team_a_id": "1", "team_b_id": "2", "team_a_totals": _t(100 + w),
           "team_b_totals": _t(90, tov=30), "team_a_category_wins": 6, "team_b_category_wins": 3, "tied_categories": 0}
          for w in (1, 2)] + [{"league_id": "L", "week": 3, "team_a_id": "1", "team_b_id": "2"}]
    (tmp_path / "matchups.json").write_text(json.dumps({"matchups": ms}), encoding="utf-8")
    live = LiveLeague("L", 3, dt.date(2026, 11, 4), "", False, "1", totals={"1": _t(10), "2": _t(50)},
                      category_wins={"1": 2, "2": 7}, opponents={"1": "2", "2": "1"})
    h = team_history(tmp_path, "L", "1", live)
    assert [r["week"] for r in h["weeks"]] == [1, 2, 3] and h["weeks"][-1]["partial"]
    assert h["weeks"][0]["result"] == {"opponent": "2", "wins": 6, "losses": 3, "ties": 0}
    assert h["weeks"][2]["ranks"]["PTS"] == 2 and h["weeks"][2]["result"]["wins"] == 2
    assert h["season"]["values"]["PTS"] == 203 and h["season"]["ranks"]["TOV"] == 1
    assert team_history(tmp_path, "L", "9")["weeks"] == []
