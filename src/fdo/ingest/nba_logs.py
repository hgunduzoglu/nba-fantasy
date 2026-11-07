"""NBA oyuncu maç kayıtları (``nba_api`` → stats.nba.com; README §13.2, §13.24).

``nba_api`` opsiyoneldir (``pip install -e ".[nba]"``). Kayıtlar ``gamelogs_nba_<sezon>.csv`` olarak yazılır;
içinde bulunulan sezonun dosyası her senkronizasyonda yenilenir (git dışı).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

COLUMNS = {"PLAYER_NAME": "name", "TEAM_ABBREVIATION": "nba_team", "GAME_DATE": "game_date", "MIN": "minutes",
           "FGM": "fgm", "FGA": "fga", "FTM": "ftm", "FTA": "fta", "FG3M": "fg3m", "PTS": "pts", "REB": "reb",
           "AST": "ast", "STL": "stl", "BLK": "blk", "TOV": "tov"}


def to_schema(raw: pd.DataFrame, season: str) -> pd.DataFrame:
    df = raw[list(COLUMNS)].rename(columns=COLUMNS)
    df["game_date"] = pd.to_datetime(df["game_date"]).dt.date.astype(str)
    df["season"] = season
    if "GAME_ID" in raw:
        df["game_id"] = raw["GAME_ID"].astype(str)
    return df


def fetch_season(season: str, timeout: int = 60) -> pd.DataFrame:
    """Bir normal sezonun bütün oyuncu maç satırları (ör. ``2026-27``)."""
    from nba_api.stats.endpoints import playergamelogs

    raw = playergamelogs.PlayerGameLogs(season_nullable=season, season_type_nullable="Regular Season",
                                        timeout=timeout).get_data_frames()[0]
    return to_schema(raw, season)


def season_file(directory: str | Path, season: str) -> Path:
    return Path(directory) / f"gamelogs_nba_{season}.csv"


def refresh_season(directory: str | Path, season: str) -> str:
    """İçinde bulunulan sezonun kayıtlarını yeniler; hata senkronizasyonu düşürmez, açıklama olarak döner."""
    try:
        df = fetch_season(season)
    except Exception as e:  # noqa: BLE001 — ayrı kaynak (stats.nba.com otomatik isteği reddedebilir)
        return f"NBA maç kayıtları alınamadı: {e}"
    if df.empty:
        return "NBA maç kayıtları boş geldi; eski dosya korundu."
    path = season_file(directory, season)
    df.to_csv(path, index=False)
    return f"NBA maç kayıtları: {len(df)} satır, son maç {df['game_date'].max()} → {path.name}"
