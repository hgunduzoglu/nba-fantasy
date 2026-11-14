"""İleriye dönük test yardımcıları (``fdo.evaluation.forward``)."""
from __future__ import annotations

import datetime as dt
import json

import pandas as pd
import pytest

from fdo.evaluation.forward import realized, snapshot_dir, summary, value, value_scales

D = dt.date(2026, 11, 1)
PLAYERS = pd.DataFrame({"name": ["Ann Able", "Bob Baker"], "nba_team": ["AAA", "BBB"]}, index=["1", "2"])


def _logs() -> pd.DataFrame:
    rows = [{"name": "Ann Able", "nba_team": "AAA", "game_date": D + dt.timedelta(days=i), "minutes": 30, "fgm": 5,
             "fga": 10, "ftm": 2, "fta": 2, "fg3m": 1, "pts": 13, "reb": 5, "ast": 3, "stl": 1, "blk": 0, "tov": 2}
            for i in range(3)]
    rows.append({**rows[0], "name": "Bob Baker", "nba_team": "BBB", "minutes": 0, "fgm": 0, "fga": 0, "ftm": 0,
                 "fta": 0, "fg3m": 0, "pts": 0, "reb": 0, "ast": 0, "stl": 0, "tov": 0})
    rows.append({**rows[0], "name": "Nobody Known", "nba_team": "CCC"})
    return pd.DataFrame(rows)


def test_realized_counts_games_played_in_the_window_and_reports_unknown_names():
    real, missing = realized(_logs(), PLAYERS, D, D + dt.timedelta(days=1))
    assert missing == 1
    assert real.loc["1", "games"] == 2 and real.loc["1", "pts"] == 26
    assert real.loc["2", "games"] == 0                                    # dakikasız kayıt maç sayılmaz


def test_value_rewards_production_and_penalises_turnovers():
    t = pd.DataFrame({"fgm": [5, 5], "fga": [10, 10], "ftm": [2, 2], "fta": [2, 2], "fg3m": [1, 1], "pts": [13, 20],
                      "reb": [5, 5], "ast": [3, 3], "stl": [1, 1], "blk": [0, 0], "tov": [2, 2], "games": [1, 1]},
                     index=["a", "b"])
    s = value_scales(t)
    v = value(t, s)
    assert v["b"] > v["a"]
    worse = value(t.assign(tov=[5, 2]), s)
    assert worse["a"] < v["a"]


def test_summary_measures_sign_agreement_and_rank_correlation():
    pairs = pd.DataFrame({"model": [1, -1, 2, -2], "forecast": [1, 1, 1, 1], "realized": [2, -1, 3, 1]})
    out = summary(pairs)
    assert out["n"] == 4 and out["model_sign"] == pytest.approx(.75) and out["forecast_sign"] == pytest.approx(.75)
    assert summary(pairs.iloc[:0]) == {"n": 0}


def test_snapshot_dir_uses_the_days_files_and_drops_later_reports(tmp_path):
    data = tmp_path / "real"
    (data / "snapshots" / "2026-11-01").mkdir(parents=True)
    (data / "rosters.json").write_text(json.dumps({"roster_date": "2026-11-14"}), encoding="utf-8")
    (data / "snapshots" / "2026-11-01" / "rosters.json").write_text(json.dumps({"roster_date": "2026-11-01"}),
                                                                     encoding="utf-8")
    for d in ("2026-10-31", "2026-11-01", "2026-11-09"):
        (data / f"injuries_cbs_{d}.csv").write_text("name\n", encoding="utf-8")
    (data / "yahoo_live.json").write_text("{}", encoding="utf-8")
    work = snapshot_dir(data, D, tmp_path / "work")
    assert json.loads((work / "rosters.json").read_text(encoding="utf-8"))["roster_date"] == "2026-11-01"
    assert sorted(p.name for p in work.glob("injuries_cbs_*")) == ["injuries_cbs_2026-10-31.csv",
                                                                     "injuries_cbs_2026-11-01.csv"]
    assert not (work / "yahoo_live.json").exists()
    with pytest.raises(FileNotFoundError):
        snapshot_dir(data, dt.date(2026, 10, 1), tmp_path / "w2")
