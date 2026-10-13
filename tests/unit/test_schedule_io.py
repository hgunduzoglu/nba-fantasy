import json

import numpy as np
import pandas as pd
import yaml

from fdo.ingest.load import load_table


def test_fetch_schedule_parse_keeps_regular_season():
    from fetch_nba_schedule import parse

    payload = {"leagueSchedule": {"seasonYear": "2026-27", "gameDates": [
        {"gameDate": "10/04/2026 00:00:00", "games": [
            {"gameId": "0012600001", "gameDateEst": "2026-10-04T00:00:00Z",
             "homeTeam": {"teamTricode": "BOS"}, "awayTeam": {"teamTricode": "NYK"}}]},
        {"gameDate": "10/20/2026 00:00:00", "games": [
            {"gameId": "0022600001", "gameDateEst": "2026-10-20T00:00:00Z",
             "homeTeam": {"teamTricode": "BOS"}, "awayTeam": {"teamTricode": "NYK"}},
            {"gameId": "0022600002", "gameDateEst": "2026-10-20T00:00:00Z",
             "homeTeam": {"teamTricode": "LAL"}, "awayTeam": {"teamTricode": "GSW"}}]},
    ]}}
    df = parse(json.loads(json.dumps(payload)))
    assert len(df) == 2 and set(df["game_date"]) == {"2026-10-20"}
    assert list(df.columns) == ["game_date", "home_team", "away_team", "game_id"]


def test_load_table_requires_manifest_and_types(tmp_path):
    csv = tmp_path / "schedule_x.csv"
    pd.DataFrame({"game_date": ["2026-10-20"], "home_team": ["BOS"], "away_team": ["NYK"]}).to_csv(csv, index=False)
    df, man, rep = load_table(csv, "schedule")
    assert df is None and not rep.ok                           # manifest yok
    (tmp_path / "manifests").mkdir()
    (tmp_path / "manifests" / "schedule_x.csv.yaml").write_text(yaml.safe_dump({
        "kind": "schedule", "source_name": "test", "retrieved_at": "2026-10-13",
        "license_status": "personal_use_confirmed", "is_synthetic": True}), encoding="utf-8")
    df, man, rep = load_table(csv, "schedule")
    assert rep.ok and df.loc[0, "game_date"] == "2026-10-20" and man["kind"] == "schedule"


def test_utilization_script_uses_calendar(config):
    from estimate_utilization import simulate

    from fdo.roster.eligibility import parse_positions
    from fdo.schedule import build_calendar

    sched = pd.DataFrame({"game_date": ["2026-10-20", "2026-10-21"], "home_team": ["BOS", "BOS"],
                          "away_team": ["NYK", "LAL"]})
    cal = build_calendar(sched, config)
    roster = (np.array(["BOS", "NYK"]), [parse_positions("C"), parse_positions("C")], np.array([1.0, 1.0]))
    res = simulate([roster], config, 0, np.random.default_rng(0), cal=cal)
    assert res["daily_today"] == 1.0
