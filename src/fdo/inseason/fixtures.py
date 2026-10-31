"""H2H fikstürleri: ``fixtures*.csv`` (league_id, team_id, week, opponent_team_id) ve
``league_info.json`` içindeki ``schedules.teams``. Bir takımın fikstürü rakibinkini de verir
(A–B eşleşmesi B–A olarak tamamlanır)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

COLUMNS = ["league_id", "team_id", "week", "opponent_team_id"]


def load_fixtures(directory: str | Path) -> pd.DataFrame:
    directory = Path(directory)
    frames = []
    for path in sorted(directory.glob("fixtures*.csv")):
        df = pd.read_csv(path, dtype=str)
        if set(COLUMNS) <= set(df.columns):
            frames.append(df[COLUMNS])
    info = directory / "league_info.json"
    if info.exists():
        data = json.loads(info.read_text(encoding="utf-8-sig"))
        rows = [{"league_id": str(lg["league_id"]), "team_id": str(t["team_id"]), "week": str(w["week"]),
                 "opponent_team_id": str(w["opponent_team_id"])}
                for lg in data.get("leagues", []) for t in (lg.get("schedules") or {}).get("teams", [])
                for w in t.get("weeks", []) if w.get("opponent_team_id")]
        if rows:
            frames.append(pd.DataFrame(rows))
    if not frames:
        return pd.DataFrame(columns=COLUMNS).astype({"week": int})
    df = pd.concat(frames, ignore_index=True).astype(str)
    mirror = df.rename(columns={"team_id": "opponent_team_id", "opponent_team_id": "team_id"})
    df = pd.concat([df, mirror[COLUMNS]], ignore_index=True)
    df["week"] = df["week"].astype(int)
    return df.drop_duplicates(["league_id", "team_id", "week"]).reset_index(drop=True)


def opponent(fixtures: pd.DataFrame, league_id: str, team_id: str, week: int) -> str | None:
    hit = fixtures[(fixtures["league_id"] == str(league_id)) & (fixtures["team_id"] == str(team_id))
                   & (fixtures["week"] == int(week))]
    return str(hit["opponent_team_id"].iloc[0]) if len(hit) else None
